#!/usr/bin/python
import configparser
import datetime
import inspect
import logging
import os
import pickle
import random
import smtplib
import socket
import sys
import time
from email.message import EmailMessage
from logging.handlers import RotatingFileHandler

import ccxt
import requests

# ------------------------------------------------------------------------------

sell_price = 0
sell_orders = []
buy_price = 0
buy_orders = []
curr_buy_order = None
curr_buy_order_size = 0
reset_counter = 0
loop = False
auto_conf = False
email_sent = 0
started = datetime.datetime.utcnow().replace(microsecond=0)
stats = None

# ------------------------------------------------------------------------------


class ExchangeConfig:
    """
    Holds the configuration read from separate .txt file.
    """
    def __init__(self, filename: str):

        config = configparser.RawConfigParser()
        config.read(filename + ".txt")

        try:
            props = dict(config.items('config'))
            self.bot_instance = filename
            self.bot_version = "1.12.5"
            self.exchange = props['exchange'].strip('"').lower()
            self.api_key = props['api_key'].strip('"')
            self.api_secret = props['api_secret'].strip('"')
            self.test = bool(props['test'].strip('"').lower() == 'true')
            self.pair = props['pair'].strip('"')
            self.symbol = props['symbol'].strip('"')
            self.order_btc_min = float(props['order_btc_min'].strip('"'))
            self.satoshi_factor = 0.00000001
            self.change = abs(float(props['change'].strip('"')))
            self.divider = abs(int(props['divider'].strip('"')))
            if self.divider < 1:
                self.divider = 1
            self.spread_factor = abs(float(props['spread_factor'].strip('"')))
            currency = self.pair.split("/")
            self.base = currency[0]
            self.quote = currency[1]
            self.send_emails = bool(props['send_emails'].strip('"').lower() == 'true')
            self.recipient_addresses = props['recipient_addresses'].strip('"').replace(' ', '').split(",")
            self.sender_address = props['sender_address'].strip('"')
            self.sender_password = props['sender_password'].strip('"')
            self.mail_server = props['mail_server'].strip('"')
        except (configparser.NoSectionError, KeyError):
            raise SystemExit('invalid configuration for ' + filename)


class OpenOrdersSummary:
    """
    Creates and holds an open orders summary
    """
    def __init__(self, open_orders):
        self.orders = []
        self.sell_orders = []
        self.buy_orders = []
        self.total_sell_order_value = 0
        self.total_buy_order_value = 0

        if len(open_orders):
            for oo in open_orders:
                o = Order(oo)
                self.orders.append(o)
                if o.side == 'sell':
                    if conf.exchange == 'kraken':
                        self.total_sell_order_value += o.amount * o.price
                    else:
                        self.total_sell_order_value += o.amount
                    self.sell_orders.append(o)
                elif o.side == 'buy':
                    if conf.exchange == 'kraken':
                        self.total_buy_order_value += o.amount * o.price
                    else:
                        self.total_buy_order_value += o.amount
                    self.buy_orders.append(o)
                else:
                    log.error(inspect.stack()[1][3], ' ?!?')

            self.sell_orders = sorted(self.sell_orders, key=lambda order: order.price, reverse=True)  # desc
            self.buy_orders = sorted(self.buy_orders, key=lambda order: order.price, reverse=True)  # desc


class Order:
    """
    Creates and holds the relevant data of an order
    """
    def __init__(self, order):
        self.id = order['id']
        self.price = order['price']
        self.amount = order['amount']
        self.side = order['side']
        self.datetime = order['datetime']

    def __str__(self):
        return "{0} order id: {1}, price: {2}, amount: {3}, created: {4}".format(self.side, self.id, self.price,
                                                                                 self.amount, self.datetime)


class Stats:
    """
    Holds the daily statistics in a ring memory (today plus the previous two)
    """
    def __init__(self, day_of_year: int, data: dict):
        self.days = []
        self.add_day(day_of_year, data)

    def add_day(self, day_of_year: int, data: dict):
        existing = self.get_day(day_of_year)
        if existing is not None:
            self.days.remove(existing)
        data['day'] = day_of_year
        if len(self.days) > 2:
            self.days = sorted(self.days, key=lambda data: data['day'], reverse=True)  # desc
            self.days.pop()
        self.days.append(data)

    def get_day(self, day_of_year: int):
        matched = filter(lambda element: element['day'] == day_of_year, self.days)
        if matched is not None:
            for day in matched:
                return day
        return None


def function_logger(console_level: int, filename: str, file_level: int = None):
    function_name = inspect.stack()[1][3]
    logger = logging.getLogger(function_name)
    # By default log all messages
    logger.setLevel(logging.DEBUG)

    # StreamHandler logs to console
    ch = logging.StreamHandler()
    ch.setLevel(console_level)
    ch_format = logging.Formatter('%(message)s')
    ch.setFormatter(ch_format)
    logger.addHandler(ch)

    if file_level is not None:
        fh = RotatingFileHandler("{0}.log".format(filename), mode='a', maxBytes=5 * 1024 * 1024, backupCount=4,
                                 encoding=None, delay=0)
        fh.setLevel(file_level)
        fh_format = logging.Formatter('%(asctime)s - %(lineno)4d - %(levelname)-8s - %(message)s')
        fh.setFormatter(fh_format)
        logger.addHandler(fh)

    return logger


def buy_executed(price: float, amount: int):
    """
    Check if the most recent buy order has been executed.
    input: current price and amount to trade (Current Balance / divider)
    output: if the most recent buy order is still open,
    the output is print statements containing the amount were trying to buy for which price.
    Else if the order is closed, we follow with the followup function and createbuyorder and
    pass on the variables we got from input.
    """
    global curr_buy_order_size
    global buy_orders

    if curr_buy_order is None:
        status = 'closed'
        log.info('Closed inexisting compensation order')
    else:
        status = fetch_order_status(curr_buy_order.id)
    log.debug('-------------------------------')
    log.debug(time.ctime())
    if status == 'open':
        log.debug('Open Buy Order! Amount: {} @ {}'.format(curr_buy_order_size, buy_price))
        log.debug('Current Price: {}'.format(price))
    elif status in ['closed', 'canceled']:
        log.info('Buy executed, starting follow up')
        if curr_buy_order in buy_orders:
            buy_orders.remove(curr_buy_order)
        # default case: use amount of last (previous) buy order for next sell order
        # else last buy was compensation order: use same amount for next sell order as the buy order to be created next
        last_buy_size = curr_buy_order_size if curr_buy_order is not None else amount
        if create_buy_order(price, amount):
            create_sell_order(last_buy_size)
        else:
            log.warning('Resetting')
            init_orders(True, False)
    else:
        log.warning('You should not be here, order state: ' + status)


def sell_executed(price: float, amount: int):
    """
    Check if any of the open sell orders has been executed.
    input: current price and amount to trade (Current Balance / divider)
    output: loop through all open sell orders and check if one has been executed. If no, exit with print statement.
    Else if it has been executed, remove the order from the list of open orders,
    cancel it on Bitmex and create a new buy order.
    """
    global sell_orders

    for order in sell_orders:
        time.sleep(0.5)
        status = fetch_order_status(order.id)
        if status == 'open':
            log.debug('Sell still ' + status)
        elif status in ['closed', 'canceled']:
            if order in sell_orders:
                sell_orders.remove(order)
            log.info('Sell executed')
            if len(sell_orders) == 0:
                create_divided_sell_order()
            cancel_current_buy_order()
            if not create_buy_order(price, amount):
                log.warning('Resetting')
                init_orders(True, False)
        else:
            log.warning('You should not be here, order state: ' + status)


def cancel_current_buy_order():
    """
    Cancels the current buy order
    """
    global curr_buy_order

    if curr_buy_order is not None:
        cancel_order(curr_buy_order)
        if curr_buy_order in buy_orders:
            buy_orders.remove(curr_buy_order)
        log.info('Canceled current ' + str(curr_buy_order))
        curr_buy_order = None if not buy_orders else buy_orders[0]


def create_sell_order(fixed_order_size: int = None):
    """
    Loop that starts after buy order is executed and sends sell order to exchange
    as well as appends the orderID to the sell_orders list.
    """
    global sell_price
    global curr_buy_order_size
    global sell_orders

    order_size = curr_buy_order_size if fixed_order_size is None else fixed_order_size

    stock = get_used_balance()
    if stock < order_size:
        # sold out - the main loop will re-init if there are no other sell orders open
        log.warning('Not executing sell order over {0} (only {1} left)'.format(float(order_size), float(stock)))
        return

    try:
        if not is_order_below_limit(order_size, sell_price):
            if conf.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase', 'liquid']:
                new_order = exchange.create_limit_sell_order(conf.pair, order_size, sell_price)
            elif conf.exchange == 'kraken':
                rate = get_current_price()
                new_order = exchange.create_limit_sell_order(conf.pair, to_kraken(order_size, rate), sell_price,
                                                             {'leverage': 2})
            order = Order(new_order)
            sell_orders.append(order)
            log.info('Created ' + str(order))

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        # insufficient funds
        if "nsufficient" in str(error.args):
            log.error('Insufficient funds - not selling ' + str(order_size))
            return
        log.error('Got an error ' + type(error).__name__ + str(error.args) + ', retrying in about 5 seconds...')
        sell_price = round(get_current_price() * (1 + conf.change))
        return create_sell_order(fixed_order_size)


def create_divided_sell_order():
    """
    Loop that starts after buy order is executed and sends sell order to exchange
    as well as appends the orderID to the sell_orders list.
    """
    global sell_orders
    global sell_price

    try:
        used_bal = get_used_balance()
        amount = round(used_bal / conf.divider)

        if not is_order_below_limit(amount, sell_price):
            if conf.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase', 'liquid']:
                new_order = exchange.create_limit_sell_order(conf.pair, amount, sell_price)
            elif conf.exchange == 'kraken':
                rate = get_current_price()
                new_order = exchange.create_limit_sell_order(conf.pair, to_kraken(amount, rate), sell_price,
                                                             {'leverage': 2})
            order = Order(new_order)
            sell_orders.append(order)
            log.info('Created ' + str(order))

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        # insufficient funds
        if "nsufficient" in str(error.args):
            log.error('Insufficient funds - not selling ' + str(amount))
            return
        log.error('Got an error ' + type(error).__name__ + str(error.args) + ', retrying in about 5 seconds...')
        sell_price = round(get_current_price() * (1 + conf.change))
        return create_divided_sell_order()


def fetch_order_status(order_id: str):
    """
    Fetches the status of an order
    input: id of an order
    output: status of the order (open, closed)
    """
    try:
        return exchange.fetch_order_status(order_id)

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        log.error('Got an error ' + type(error).__name__ + str(error.args) + ', retrying in about 5 seconds...')
        sleep_for(4, 6)
        return fetch_order_status(order_id)


def cancel_order(order: Order):
    """
    Cancels an order
    """
    try:
        if order is not None:
            status = exchange.fetch_order_status(order.id)
            if status == 'open':
                exchange.cancel_order(order.id)
            else:
                log.warning('Order to be canceled {0} was in state '.format(order.id) + status)

    except ccxt.OrderNotFound as error:
        log.error('Order to be canceled not found ' + order.id + error.args)
        return
    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        log.error('Got an error ' + type(error).__name__ + str(error.args) + ', retrying in about 5 seconds...')
        sleep_for(4, 6)
        return cancel_order(order)


def create_buy_order(price: float, amount: int):
    """
    Creates a buy order and sets the values as global ones. Used by other functions.
    :param price current price of BTC
    :param amount the order volume
    output: calculate the price to get long (price + change) and to get short (price - change).
    In addition set the current orderID and current order size as global values.
    If the amount is below the order limit or there is not enough margin and there are open sell orders, the function
    is going to sleep, allowing sell orders to be filled - afterwards the amount is recalculated and the function calls
    itself with the new amount
    """
    global sell_price
    global buy_price
    global curr_buy_order_size
    global curr_buy_order
    global buy_orders

    buy_price = round(price * (1 - conf.change))
    sell_price = round(price * (1 + conf.change))
    curr_buy_order_size = amount
    cur_btc_price = get_current_price()

    try:
        if not is_order_below_limit(amount, buy_price):
            if conf.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase', 'liquid']:
                new_order = exchange.create_limit_buy_order(conf.pair, amount, buy_price)
            elif conf.exchange == 'kraken':
                new_order = exchange.create_limit_buy_order(conf.pair, to_kraken(amount, cur_btc_price), buy_price,
                                                            {'leverage': 2, 'oflags': 'fcib'})
            order = Order(new_order)
            log.info('Created ' + str(order))
            curr_buy_order = order
            buy_orders.append(order)
            return True
        elif len(sell_orders) > 0:
            log.info('Could not create buy order, waiting for a sell order to be realised')
            return delay_buy_order(cur_btc_price, price)
        else:
            log.warning('Could not create buy order over {0} and there are no open sell orders, reset required'
                        .format(str(amount)))
            return False

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        # insufficient margin || margin level too low
        if "nsufficient" in str(error.args) or "too low" in str(error.args):
            if len(sell_orders) > 0:
                log.info(
                    'Could not create buy order over {0}, insufficient margin, waiting for a sell order to be realised'.format(
                        str(amount)))
                return delay_buy_order(cur_btc_price, price)
            else:
                log.warning('Could not create buy order over {0}, insufficient margin'.format(str(amount)))
                return False
        else:
            log.error('Got an error ' + type(error).__name__ + str(error.args) + ', retrying in about 5 seconds...')
            sleep_for(4, 6)
            return create_buy_order(update_price(cur_btc_price, price), amount)


def delay_buy_order(cur_btc_price: float, price: float):
    """
    Delays the creation of a buy order, allowing sell orders to be filled - afterwards the amount is recalculated and
    the function calls create_buy_order with the current btc price and the new amount
    :param cur_btc_price: the btc with which price was calculated
    :param price: the price of the original buy order to be created
    """
    sleep_for(60, 120)
    daily_report()
    new_amount = round(get_balance()['free'] / conf.divider * get_current_price())  # recalculate order size
    return create_buy_order(update_price(cur_btc_price, price), new_amount)


def create_market_sell_order(amount_btc: float):
    """
    Creates a market sell order and sets the values as global ones. Used to compensate margins above 50%.
    input: amount_btc to be sold to reach 50% margin
    """
    global buy_price
    global sell_price
    global sell_orders

    cur_btc_price = get_current_price()

    amount = round(amount_btc * cur_btc_price)

    buy_price = round(cur_btc_price * (1 - conf.change))
    sell_price = round(cur_btc_price * (1 + conf.change))

    try:
        if not is_btc_amount_below_limit(amount_btc):
            if conf.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase']:
                new_order = exchange.create_market_sell_order(conf.pair, amount)
            elif conf.exchange == 'kraken':
                new_order = exchange.create_market_sell_order(conf.pair, amount_btc, {'leverage': 2})
            elif conf.exchange == 'liquid':
                new_order = exchange.create_market_sell_order(conf.pair, amount, {'leverage': 2})
            order = Order(new_order)
            log.info('Created market ' + str(order))
            sell_orders.append(order)

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        # insufficient funds
        if "nsufficient" in str(error.args):
            log.error('Insufficient funds - not selling ' + str(amount))
            return
        log.error('Got an error ' + type(error).__name__ + str(error.args) + ', retrying in about 5 seconds...')
        sleep_for(4, 6)
        return create_market_sell_order(amount_btc)


def create_market_buy_order(amount_btc: float):
    """
    Creates a market buy order and sets the values as global ones. Used to compensate margins below 50%.
    input: amount_btc to be bought to reach 50% margin
    """
    global buy_price
    global sell_price
    global curr_buy_order

    cur_btc_price = get_current_price()

    amount = round(amount_btc * cur_btc_price)

    buy_price = round(cur_btc_price * (1 - conf.change))
    sell_price = round(cur_btc_price * (1 + conf.change))

    try:
        if not is_order_below_limit(amount, cur_btc_price):
            if conf.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase']:
                new_order = exchange.create_market_buy_order(conf.pair, amount)
            elif conf.exchange == 'kraken':
                new_order = exchange.create_market_buy_order(conf.pair, amount_btc, {'leverage': 2, 'oflags': 'fcib'})
            elif conf.exchange == 'liquid':
                # TODO multicurrency_or_collateral_only_used_for_margin issue
                new_order = exchange.create_market_buy_order(conf.pair, amount_btc, {'leverage': 2, 'funding_currency': 'BTC'})
            order = Order(new_order)
            log.info('Created market ' + str(order))
            curr_buy_order = None

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        if "not_enough_free" in str(error.args) and conf.exchange == 'liquid':
            log.error('Not enough free balanace ' + type(error).__name__ + str(error.args))
            return
        log.error('Got an error ' + type(error).__name__ + str(error.args) + ', retrying in about 5 seconds...')
        sleep_for(4, 6)
        return create_market_buy_order(amount_btc)


def get_margin_leverage():
    """
    Fetch the leverage
    """
    try:
        if conf.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase', 'liquid']:
            return exchange.fetch_balance()['info'][0]['marginLeverage']
        elif conf.exchange == 'kraken':
            return float(exchange.private_post_tradebalance()['result']['ml'])

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        log.error('Got an error' + type(error).__name__ + str(error.args) + ', retrying in about 5 seconds...')
        sleep_for(4, 6)
        return get_margin_leverage()


def get_wallet_balance():
    """
    Fetch the wallet balance
    """
    try:
        if conf.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase']:
            return exchange.fetch_balance()['info'][0]['walletBalance'] * conf.satoshi_factor
        elif conf.exchange == 'kraken':
            return float(exchange.private_post_tradebalance()['result']['tb'])
        elif conf.exchange == 'liquid':
            log.error("get_wallet_balance() not yet implemented for " + conf.exchange)
            # TODO check
            for b in exchange.private_get_accounts_balance():
                if b['currency'] == conf.base:
                    return b['balance']

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        log.error('Got an error' + type(error).__name__ + str(error.args) + ', retrying in about 5 seconds...')
        sleep_for(4, 6)
        return get_wallet_balance()


def get_balance():
    """
    Fetch the balance in btc.
    output: balance (used,free,total)
    """
    try:
        return exchange.fetch_balance()['BTC']

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        log.error('Got an error' + type(error).__name__ + str(error.args) + ', retrying in about 5 seconds...')
        sleep_for(4, 6)
        return get_balance()


def get_used_balance():
    """
    Fetch the used balance in btc.
    output: balance
    """
    try:
        if conf.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase']:
            return exchange.private_get_position()[0]['currentQty']
        elif conf.exchange == 'kraken':
            result = exchange.private_post_tradebalance()['result']
            return round(float(result['e']) - float(result['mf']))
        elif conf.exchange == 'liquid':
            log.error("get_used_balance() not yet implemented for " + conf.exchange)
            return None
            # TODO check
            # for b in exchange.private_get_accounts_balance():
            #     if b['currency'] == conf.base:
            #        return float(b['balance'])
            # TODO timeout issue
            # return exchange.private_get_trades()

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        log.error('Got an error ' + type(error).__name__ + str(error.args) + ', retrying in about 5 seconds...')
        sleep_for(4, 6)
        return get_used_balance()


def get_position_info():
    """
    Fetch position information
    """
    try:
        if conf.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase']:
            response = exchange.private_get_position()
            if response and response[0] and response[0]['avgEntryPrice']:
                return response[0]
            return None
        elif conf.exchange == 'kraken':
            log.error("get_position_info() not yet implemented for kraken")
            return
        elif conf.exchange == 'liquid':
            response = exchange.private_get_trading_accounts()
            for pos in response:
                if pos['currency_pair_code'] == conf.symbol:
                    return pos
            return None

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        log.error('Got an error ' + type(error).__name__ + str(error.args) + ', retrying in about 5 seconds...')
        sleep_for(4, 6)
        return get_position_info()


def compensate():
    """
    Approaches the margin used towards 50% by selling or buying the difference to market price
    """
    try:
        if conf.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase', 'liquid']:
            bal = exchange.fetch_balance()['BTC']
            if bal['used'] is None:
                bal['used'] = 0
        elif conf.exchange == 'kraken':
            bal = exchange.private_post_tradebalance({'asset': 'BTC'})['result']
            bal['free'] = float(bal['mf'])
            bal['total'] = float(bal['e'])
            bal['used'] = float(bal['m'])

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        log.error('Got an error' + type(error).__name__ + str(error.args) + ', retrying in about 5 seconds...')
        sleep_for(4, 6)
        return compensate()

    used = float(100 - (bal['free'] / bal['total']) * 100)
    if used < 40 or used > 60:
        amount_btc = float(bal['total'] / 2 - bal['used'])
        if amount_btc > 0:
            log.info("Need to buy {0} BTC in order to reach 50% margin".format(amount_btc))
            create_market_buy_order(amount_btc)
        else:
            log.info("Need to sell {0} BTC in order to reach 50% margin".format(abs(amount_btc)))
            create_market_sell_order(abs(amount_btc))
    return


def spread(market_price: float):
    """
    Checks if the difference between the highest buy order price and the market price is bigger than spread_factor times
    change and the difference of the lowest sell order to the market price is bigger spread_factor times change
    If so, then the highest buy order is canceled and a new buy and sell order are created with the configured offset
    to the market price
    """
    if len(buy_orders) > 0 and len(sell_orders) > 0:
        highest_buy_order = sorted(buy_orders, key=lambda order: order.price, reverse=True)[0]
        if highest_buy_order.price < market_price * (1 - conf.change * conf.spread_factor):
            lowest_sell_order = sorted(sell_orders, key=lambda order: order.price)[0]
            if lowest_sell_order.price > market_price * (1 + conf.change * conf.spread_factor):
                log.info("Orders above spread tolerance min sell: {0} max buy: {1} current rate: {2}".format(
                    lowest_sell_order.price, highest_buy_order.price, market_price))
                log.info("Canceling highest " + str(highest_buy_order))
                cancel_order(highest_buy_order)
                if create_buy_order(market_price, highest_buy_order.amount):
                    create_divided_sell_order()


def get_margin_balance():
    """
    Fetches the margin balance (free and total)
    """
    try:
        if conf.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase', 'liquid']:
            bal = exchange.fetch_balance()['BTC']
        elif conf.exchange == 'kraken':
            bal = exchange.private_post_tradebalance({'asset': 'EUR'})['result']
            bal['free'] = float(bal['mf'])
            bal['total'] = float(bal['e'])
        return bal

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        log.error('Got an error' + type(error).__name__ + str(error.args) + ', retrying in about 5 seconds...')
        sleep_for(4, 6)
        return get_margin_balance()


def calculate_used_margin_percentage(bal=None):
    """
    Calculates the used margin percentage
    """
    if bal is None:
        bal = get_margin_balance()
        if bal['total'] <= 0:
            return 0
    return float(100 - (bal['free'] / bal['total']) * 100)


def calc_avg_entry_price(open_orders: [Order]):
    """"
    Calculates the average entry price of the remaining amount of all open orders (required for kraken only)
    :param open_orders: [Order]
    """
    total_amount = 0
    total_price = 0
    if len(open_orders) > 0:
        for o in open_orders:
            total_amount += o.amount
            total_price += o.price * o.amount
    if total_amount > 0:
        return total_price / total_amount
    return 0


def get_current_price():
    """
    Fetch the current BTC price
    output: last bid price
    """
    sleep_for(4, 6)
    try:
        return exchange.fetch_ticker(conf.pair)['bid']

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        log.error('Got an error ' + type(error).__name__ + str(error.args) + ', retrying in about 5 seconds...')
        return get_current_price()


def update_price(origin_price: float, price: float):
    """
    Update the price by considering the old and current price
    :param origin_price:
    :param price:
    :return: price
    """
    return (get_current_price() / origin_price) * price


def init_orders(force_close: bool, auto_conf: bool):
    """
    Initialize existing orders or remove all pending ones
    output True if loaded and False if compensate margin is necessary
    :param force_close: close all orders/positions (reset)
    :param auto_conf: load all orders and keep position
    :return:
    """
    global sell_price
    global sell_orders
    global curr_buy_order_size
    global curr_buy_order
    global buy_orders
    global buy_price
    global reset_counter

    if force_close:
        reset_counter += 1

    try:
        init = ''
        if auto_conf:
            log.warning("Bot was resurrected by hades")

        # Handle open orders
        oos = get_open_orders()

        log.info("Used margin: {:>17.2f}%".format(calculate_used_margin_percentage()))
        print_position_info(oos)

        if oos.orders:
            log.info("Value of buy orders " + conf.base + ": {:>2}".format(int(oos.total_buy_order_value)))
            log.info("Value of sell orders " + conf.base + ": {:>1}".format(int(oos.total_sell_order_value)))
            log.info("No. of buy orders: {:>8}".format(len(oos.buy_orders)))
            log.info("No. of sell orders: {:>7}".format(len(oos.sell_orders)))
            log.info('-------------------------------')

            if not force_close and not auto_conf:
                init = input('There are open orders! Would you like to load them? (y/n) ')
            if not force_close and (auto_conf or init.lower() in ['y', 'yes']):
                return load_existing_orders(oos)
            else:
                log.info('Unrealised PNL: {0} BTC'.format(str(get_unrealised_pnl(conf.symbol) * conf.satoshi_factor)))
                if force_close:
                    cancel_orders(oos.orders)
                else:
                    clear_position = input('There is an open BTC position! Would you like to close it? (y/n) ')
                    if clear_position.lower() in ['y', 'yes']:
                        cancel_orders(oos.orders)
                        close_position(conf.symbol)
                    else:
                        compensate_position = input('Would you like to compensate to 50%? (y/n) ')
                        if compensate_position.lower() in ['n', 'no']:
                            # No "compensate" wanted
                            return True

        # Handle open positions if no orders are open
        elif not force_close and not auto_conf and get_open_position(conf.symbol) is not None:
            msg = 'There is an open BTC position!\nUnrealised PNL: {0:.8f} BTC\nWould you like to close it? (y/n) '
            init = input(msg.format(get_unrealised_pnl(conf.symbol) * conf.satoshi_factor))
            if init.lower() in ['y', 'yes']:
                close_position(conf.symbol)

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        log.error('Got an error ' + type(error).__name__ + str(error.args) + ', retrying in about 5 seconds...')
        sleep_for(4, 6)
        return init_orders(force_close, auto_conf)

    else:
        del oos
        log.info('Initialization complete')
        # compensate
        return False


def load_existing_orders(oos: OpenOrdersSummary):
    global sell_orders, sell_price, buy_orders, curr_buy_order, buy_price, curr_buy_order_size
    if oos.sell_orders:
        sell_orders = oos.sell_orders
        sell_price = sell_orders[0].price  # lowest if several
    if oos.buy_orders:
        buy_orders = oos.buy_orders
        curr_buy_order = buy_orders[-1]  # highest if several
        buy_price = curr_buy_order.price
        curr_buy_order_size = curr_buy_order.amount
    # All sell orders executed
    if not oos.sell_orders:
        sell_price = round(get_current_price() * (1 + conf.change))
        create_sell_order()

    # All buy orders executed
    elif not oos.buy_orders:
        create_buy_order(get_current_price(),
                         round(get_balance()['free'] / conf.divider * get_current_price()))
    del oos
    log.info('Initialization complete (using existing orders)')
    # No "compensate" necessary
    return True


def cancel_orders(orders: [Order]):
    """
    Close a list of orders
    :param orders: [Order]
    """
    try:
        for o in orders:
            log.debug('Cancel ' + str(o))
            status = exchange.fetch_order_status(o.id)
            if status == 'open':
                exchange.cancel_order(o.id)
            else:
                log.warning('Cancel ' + str(o) + ' was in state ' + status)

    except ccxt.OrderNotFound as error:
        log.error('Cancel ' + str(o) + ' not found :' + error.args)
        return
    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        log.error('Got an error ' + type(error).__name__ + str(error.args) + ', retrying in about 5 seconds...')
        sleep_for(4, 6)
        return cancel_orders(orders)


def close_position(symbol: str):
    """
    Close any open position
    """
    try:
        log.info('close position ' + symbol)
        if conf.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase', 'liquid']:
            exchange.private_post_order_closeposition({'symbol': symbol})
        elif conf.exchange == 'kraken':
            exchange.create_market_sell_order(conf.pair, 0.0, {'leverage': 2})

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        # no retry in case of "no volume to close position" (kraken specific error)
        if "volume to close position" in str(error.args):
            return
        log.error('Got an error ' + type(error).__name__ + str(error.args) + ', retrying in about 5 seconds...')
        sleep_for(4, 6)
        return close_position(symbol)


def get_open_position(symbol: str):
    """
    Get all open positions
    :return: positions
    """
    try:
        if conf.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase']:
            for p in exchange.private_get_position():
                if p['isOpen'] and p['symbol'] == symbol:
                    return p
        elif conf.exchange == 'kraken':
            a = exchange.private_post_openpositions()
            if a['result'] == 'success':
                for p in a['openPositions']:
                    if p['symbol'] == symbol:
                        return p
        elif conf.exchange == 'liquid':
            trades = exchange.private_get_trades({'status': 'open'})
            # TODO timeout issue
            # for t in exchange.private_get_trades():
            #     if ['isOpen'] and t['symbol'] == symbol:
            #         return t
            log.error('get_open_position() not yet implemented for ' + conf.exchange)
            return None
        return None

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        log.error('Got an error ' + type(error).__name__ + str(error.args) + ', retrying in about 5 seconds...')
        sleep_for(4, 6)
        return get_open_position(symbol)


def get_open_orders():
    """
    Gets all open orders
    :return: OpenOrdersSummary
    """
    try:
        return OpenOrdersSummary(exchange.fetch_open_orders(conf.pair, since=None, limit=None, params={}))

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        log.error('Got an error ' + type(error).__name__ + str(error.args) + ', retrying in about 5 seconds...')
        sleep_for(4, 6)
        return get_open_orders()


def get_unrealised_pnl(symbol: str):
    """
    Returns the unrealised pnl for the requested currency
    :param symbol:
    :return: float
    """
    try:
        if get_open_position(symbol) is not None:
            return float(get_open_position(symbol)['unrealisedPnl'])
        else:
            return 0.0

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        log.error('Got an error ' + type(error).__name__ + str(error.args) + ', retrying in about 5 seconds...')
        sleep_for(4, 6)
        return get_unrealised_pnl(symbol)


def print_position_info(oos: OpenOrdersSummary):
    if conf.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase']:
        sleep_for(1, 2)
        poi = get_position_info()
        if poi:
            log.info("Position " + conf.quote + ": {:>13}".format(poi['currentQty']))
            log.info("Entry price: {:>16.1f}".format(poi['avgEntryPrice']))
            log.info("Market price: {:>15.1f}".format(poi['markPrice']))
            log.info("Liquidation price: {:>10.1f}".format(poi['liquidationPrice']))
            del poi
        else:
            log.info("Available balance is " + conf.base + ": {:>3} ".format(get_balance()['free']))
            log.info("No position found, I will create one for you")
            return False
    elif conf.exchange == 'kraken':
        log.info("Position " + conf.quote + ": {:>13}".format(get_used_balance()))
        log.info("Entry price: {:>16.1f}".format(calc_avg_entry_price(oos.orders)))
        log.info("Market price: {:>15.1f}".format(get_current_price()))
    elif conf.exchange == 'liquid':
        poi = get_position_info()
        log.info("Position " + conf.base + ": {:>13.2f}".format(float(poi['position'])))
    if not oos.orders:
        log.info("No open orders")


def connect_to_exchange(conf: ExchangeConfig):
    """
    Connects to the exchange.
    :param conf: ExchangeConfig
    :return: exchange
    """
    exchanges = {'binance': ccxt.binance,
                 'bitfinex': ccxt.bitfinex,
                 'bitmex': ccxt.bitmex,
                 'coinbase': ccxt.coinbase,
                 'kraken': ccxt.kraken,
                 'liquid': ccxt.liquid}

    exchange = exchanges[conf.exchange]({
        'enableRateLimit': True,
        'apiKey': conf.api_key,
        'secret': conf.api_secret,
        # 'verbose': True,
    })

    # pprint(dir(exchange))

    if hasattr(conf, 'test') & conf.test:
        if 'test' in exchange.urls:
            exchange.urls['api'] = exchange.urls['test']
        else:
            raise SystemExit('Test not supported by ' + conf.exchange)

    log.info('Connecting to ' + conf.exchange)
    return exchange


def sleep_for(greater: int, less: int):
    seconds = round(random.uniform(greater, less), 3)
    time.sleep(seconds)


def is_order_below_limit(amount: int, price: float):
    return is_btc_amount_below_limit(abs(amount / price))


def is_btc_amount_below_limit(amount_btc: float):
    if abs(amount_btc) < conf.order_btc_min:
        log.info('Per order volume below limit: ' + str(abs(amount_btc)))
        return True
    return False


def to_kraken(amount: int, price: float):
    return round(amount / price, 8)


def write_control_file(filename: str):
    with open(filename + '.pid', 'w') as f:
        f.write(str(os.getpid()) + ' ' + filename)


def daily_report():
    """
    Creates a daily report email around 12:10 UTC
    """
    global email_sent

    if conf.send_emails:
        now = datetime.datetime.utcnow()
        if datetime.datetime(2012, 1, 17, 12, 15).time() > now.time() \
                > datetime.datetime(2012, 1, 17, 12, 10).time() and email_sent != now.day:
            subject = "Daily report for {0}".format(conf.bot_instance)
            send_mail(subject, create_mail_content())
            email_sent = now.day


def create_mail_content():
    """
    Fetches the data required for the daily report email
    :return: mailcontent: str
    """

    performance_part = create_mail_part_performance()
    advice_part = create_mail_part_advice()
    settings_part = create_mail_part_settings()
    general_part = create_mail_part_general()

    performance = ["Performance", "-----------", '\n'.join(performance_part) + '\n* (change within 24 hours, 48 hours)', '\n\n']
    advice = ["Assessment / advice", "-------------------", '\n'.join(advice_part), '\n\n']
    settings = ["Your settings", "-------------", '\n'.join(settings_part), '\n\n']
    general = ["General", "-------", '\n'.join(general_part), '\n\n']

    bcs_url = 'https://bitcoin-schweiz.ch/bot/'
    text = '\n'.join(performance) + '\n'.join(advice) + '\n'.join(settings) + '\n'.join(general) + bcs_url

    csv = conf.bot_instance + ';' + str(datetime.datetime.utcnow().replace(microsecond=0)) + ' UTC;' + (';'.join(performance_part) + ';' + ';'.join(
        advice_part) + ';' + ';'.join(settings_part) + '\n').replace('  ', '').replace(':', ':;')

    with open(conf.bot_instance + '.csv', 'a') as f:
        f.write(csv)

    return text + csv


def create_mail_part_settings():
    return ["Change/difference: {:>11.1f}%".format(conf.change*100),
            "Share/quota: {:>17}".format('1/' + str(conf.divider))]


def create_mail_part_general():
    general = ["No. of resets: {:>15}".format(reset_counter)]
    if auto_conf:
        general.append("Bot was resurrected at: {0} UTC".format(started))
    else:
        general.append("Bot running since: {0} UTC".format(started))
    general.append("{0}@{1}: ".format(conf.bot_instance, socket.gethostname()) + str(datetime.datetime.utcnow().replace(microsecond=0)) + " UTC")
    general.append("Version: {:>21}".format(conf.bot_version))
    return general


def create_mail_part_advice():
    part = []
    append_mayer(part)
    return part


def create_mail_part_performance():
    part = []
    append_balances(part)
    append_orders(part)
    return part


def append_orders(part: []):
    oos = get_open_orders()
    part.append("Value of buy orders " + conf.quote + ": {:>5}".format(int(oos.total_buy_order_value)))
    part.append("Value of sell orders " + conf.quote + ": {:>4}".format(int(oos.total_sell_order_value)))
    part.append("No. of buy orders: {:>11}".format(len(oos.buy_orders)))
    part.append("No. of sell orders: {:>10}".format(len(oos.sell_orders)))


def append_balances(part: []):
    """
    Adds liquidation price, wallet balance, margin balance (including stats), used margin and leverage information
    """
    bal = get_margin_balance()
    sleep_for(2, 3)

    if conf.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase', 'liquid']:
        sleep_for(1, 2)
        poi = get_position_info()
        sleep_for(1, 2)
        part.append("Wallet balance " + conf.base + ": {:>13.4f}".format(get_wallet_balance()))
        append_price_and_margin_change(bal, part, conf.base)
        part.append("Liquidation price: {:>11.1f}".format(poi['liquidationPrice']))
        part.append("Used margin: {:>18.2f}%".format(calculate_used_margin_percentage(bal)))
        part.append("Effective leverage: {:>11.2f}x".format(get_margin_leverage()))

    elif conf.exchange == 'kraken':
        append_price_and_margin_change(bal, part, conf.quote)
        part.append("Used margin: {:>18.2f}%".format(calculate_used_margin_percentage(bal)))
        part.append("Effective leverage: {:>11.1f}%".format(get_margin_leverage()))

    part.append("Position " + conf.quote + ": {:>16}".format(get_used_balance()))


def append_price_and_margin_change(bal: dict, part: [], currency: str):
    price = get_current_price()
    today = calculate_daily_statistics(bal['total'], price)

    formatter = 13.4 if currency == conf.base else 12.2
    m_bal = "Margin balance " + currency + ": {0:>{1}f}".format(today['mBal'], formatter)
    if 'mBalChan24' in today:
        m_bal += " ("
        m_bal += "{0:{1}.2f}%".format(today['mBalChan24'], '+' if today['mBalChan24'] else '')
        if 'mBalChan48' in today:
            m_bal += ", {0:{1}.2f}%".format(today['mBalChan48'], '+' if today['mBalChan48'] else '')
        m_bal += ")*"
    part.append(m_bal)

    rate = conf.base + " price " + conf.quote + ": {:>16.2f}".format(price)
    if 'priceChan24' in today:
        rate += " ("
        rate += "{0:{1}.2f}%".format(today['priceChan24'], '+' if today['priceChan24'] else '')
        if 'priceChan48' in today:
            rate += ", {0:{1}.2f}%".format(today['priceChan48'], '+' if today['priceChan48'] else '')
        rate += ")*"
    part.append(rate)


def send_mail(subject: str, content: str):
    recipients = ", ".join(conf.recipient_addresses)
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = conf.sender_address
    msg['To'] = recipients
    msg.set_content(content)

    server = smtplib.SMTP(conf.mail_server, 587)
    server.set_debuglevel(0)
    server.login(conf.sender_address, conf.sender_password)
    server.send_message(msg)
    server.quit()
    log.info("Sent email to {0}".format(recipients))


def calculate_daily_statistics(m_bal: float, price: float):
    """
    Calculates, updates and persists the change in the margin balance compared with yesterday
    :param m_bal: todays margin balance
    :param price: the current rate
    :return: todays statistics including price and margin balance changes compared with 24 and 48 hours ago
    """
    global stats

    today = {'mBal': m_bal, 'price': price}
    if stats is None:
        stats = Stats(int(datetime.date.today().strftime("%j")), today)
        persist_statistics()
    else:
        stats.add_day(int(datetime.date.today().strftime("%j")), today)
        persist_statistics()
        before_24h = stats.get_day(int(datetime.date.today().strftime("%j"))-1)
        if before_24h is not None:
            today['mBalChan24'] = round((today['mBal']/before_24h['mBal']-1) * 100, 2)
            if 'price' in before_24h:
                today['priceChan24'] = round((today['price']/before_24h['price']-1) * 100, 2)
            before_48h = stats.get_day(int(datetime.date.today().strftime("%j"))-2)
            if before_48h is not None:
                today['mBalChan48'] = round((today['mBal']/before_48h['mBal']-1) * 100, 2)
                if 'price' in before_48h:
                    today['priceChan48'] = round((today['price']/before_48h['price']-1) * 100, 2)
    return today


def load_statistics():
    content = None
    stats_file = conf.bot_instance + '.pkl'
    if os.path.isfile(stats_file):
        with open(stats_file, "rb") as f:
            content = pickle.load(f)
    return content


def persist_statistics():
    stats_file = conf.bot_instance + '.pkl'
    with open(stats_file, "wb") as f:
        pickle.dump(stats, f)


def fetch_mayer(tries: int = 0):
    try:
        r = requests.get('https://mayermultiple.info/current.json')
        return r.json()['data']['current_mayer_multiple']

    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, requests.exceptions.ReadTimeout) as error:
        log.error('Got an error ' + type(error).__name__ + str(error.args) + ', retrying in about 5 seconds...')
        sleep_for(4, 6)
        return fetch_mayer(tries+1) if tries < 4 else None


def print_mayer():
    mayer = fetch_mayer()
    if mayer is not None:
        mayer = float(mayer)
        if mayer < 1.39:
            return "Mayer multiple: {:>15.2f} (low: buy)".format(mayer)
        elif mayer > 2.4:
            return "Mayer multiple: {:>15.2f} (high: sell)".format(mayer)
        else:
            return "Mayer multiple: {:>15.2f} (hold)".format(mayer)
    return


def append_mayer(part: []):
    text = print_mayer()
    if text is not None:
        part.append(text)


# ------------------------------------------------------------------------------
if __name__ == '__main__':
    print('Starting Hold n Trade Bot')
    print('ccxt version:', ccxt.__version__)

    if len(sys.argv) > 1:
        filename = os.path.basename(sys.argv[1])
        if len(sys.argv) > 2:
            if sys.argv[2] == '-ac':
                auto_conf = True
    else:
        filename = os.path.basename(input('Filename with API Keys (config): ') or 'config')

    write_control_file(filename)
    log = function_logger(logging.DEBUG, filename, logging.INFO)
    log.info('-------------------------------')
    conf = ExchangeConfig(filename)
    log.info('Holdntrade version: {0}'.format(conf.bot_version))
    exchange = connect_to_exchange(conf)
    stats = load_statistics()

    loop = init_orders(False, auto_conf)

    while True:
        market_price = get_current_price()
        amount = round(get_balance()['free'] / conf.divider * market_price)

        if loop:
            daily_report()
            buy_executed(market_price, amount)
            sell_executed(market_price, amount)
            if len(sell_orders) == 0:
                log.info('No sell orders, resetting all orders')
                loop = init_orders(True, False)
            else:
                spread(market_price)

        if not loop:
            compensate()
            loop = True
