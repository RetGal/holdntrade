#!/usr/bin/python
import configparser
import datetime
import inspect
import logging
import os
import random
import smtplib
import sys
import time
from email.message import EmailMessage
from logging.handlers import RotatingFileHandler

import ccxt

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
started = datetime.datetime.utcnow()

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
            self.bot_version = "1.11.3"
            self.exchange = props['exchange'].strip('"').lower()
            self.api_key = props['api_key'].strip('"')
            self.api_secret = props['api_secret'].strip('"')
            self.test = bool(props['test'].strip('"').lower() == 'true')
            self.pair = props['pair'].strip('"')
            self.symbol = props['symbol'].strip('"')
            self.satoshi_factor = float(props['satoshi_factor'].strip('"'))
            self.change = float(props['change'].strip('"'))
            self.divider = abs(float(props['divider'].strip('"')))
            if self.divider < 1:
                self.divider = 1
            self.spread_factor = float(props['spread_factor'].strip('"'))
            self.order_btc_min = float(props['order_btc_min'].strip('"'))
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

        self.orders = open_orders
        self.sell_orders = []
        self.buy_orders = []
        self.total_sell_order_value = 0
        self.total_buy_order_value = 0

        if len(open_orders):
            for o in open_orders:
                if o['side'] == 'sell':
                    if conf.exchange == 'kraken':
                        self.total_sell_order_value += o['amount'] * o['price']
                    else:
                        self.total_sell_order_value += o['amount']
                    self.sell_orders.append(Order(o))
                elif o['side'] == 'buy':
                    if conf.exchange == 'kraken':
                        self.total_buy_order_value += o['amount'] * o['price']
                    else:
                        self.total_buy_order_value += o['amount']
                    self.buy_orders.append(Order(o))
                else:
                    log.error(inspect.stack()[1][3], ' ?!?')

                self.sell_orders = sorted(self.sell_orders, key=lambda order: order.price, reverse=True)  # desc
                self.buy_orders = sorted(self.buy_orders, key=lambda order: order.price, reverse=True)  # desc


class Order:
    """
    Creates and holds an open orders summary
    """
    def __init__(self, order):

        self.id = order['id']
        self.price = order['price']
        self.amount = order['amount']
        self.side = order['side']
        self.datetime = order['datetime']


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


def trade_executed(price: float, amount: int):
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
        log.info('Trade executed, starting follow up')
        cancel_current_buy_order()
        last_buy_size = curr_buy_order_size
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
        log.info('Canceled current buy order id: {0} price: {1} amount: {2} '
                 .format(curr_buy_order.id, curr_buy_order.price, curr_buy_order.amount))
        if not buy_orders:
            curr_buy_order = None
        else:
            curr_buy_order = buy_orders[0]


def create_sell_order(fixed_order_size: int = None):
    """
    Loop that starts after buy order is executed and sends sell order to exchange
    as well as appends the orderID to the sell_orders list.
    """
    global sell_price
    global curr_buy_order_size
    global sell_orders

    if fixed_order_size is None:
        order_size = curr_buy_order_size
    else:
        order_size = fixed_order_size

    stock = get_used_balance()
    if stock < order_size:
        # sold out - the main loop will re-init if there are no other sell orders open
        log.warning('Not executing sell order over {0} (only {1} left)'.format(str(order_size), str(stock)))
        return

    try:
        if not is_order_below_limit(order_size, sell_price):
            if conf.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase', 'liquid']:
                new_order = exchange.create_limit_sell_order(conf.pair, order_size, sell_price)
            elif conf.exchange == 'kraken':
                rate = get_current_price()
                new_order = exchange.create_limit_sell_order(conf.pair, to_kraken(order_size, rate), sell_price,
                                                             {'leverage': 2})
            log.info('Created ' + str(new_order))
            sell_orders.append(Order(new_order))

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
            log.info('Created ' + str(new_order))
            sell_orders.append(Order(new_order))

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        # insufficient funds
        if "nsufficient" in str(error.args):
            log.error('Insufficient funds - not selling ' + str(amount))
            return
        log.error('Got an error ' + type(error).__name__ + str(error.args) + ', retrying in about 5 seconds...')
        sell_price = round(get_current_price() * (1 + conf.change))
        return create_divided_sell_order()


def fetch_order_status(orderId: str):
    """
    Fetches the status of an order
    input: id of an order
    output: status of the order (open, closed)
    """
    try:
        fo = exchange.fetch_order_status(orderId)

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        log.error('Got an error ' + type(error).__name__ + str(error.args) + ', retrying in about 5 seconds...')
        sleep_for(4, 6)
        return fetch_order_status(orderId)
    else:
        return fo


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
    If the amount is below the order limit and there are open sell orders, the function is going to sleep, allowing
    sell orders to be filled - afterwards the amount is recalculated and the function calls itself with the new amount
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

            log.info('Created ' + str(new_order))
            order = Order(new_order)
            curr_buy_order = order
            buy_orders.append(order)

            return True
        elif len(sell_orders) > 0:
            log.warning('Could not create buy order, waiting for a sell order to be realised')
            sleep_for(60, 120)
            daily_report()
            # recalculate order size
            amount = round(get_balance()['free'] / conf.divider * get_current_price())
            return create_buy_order(update_price(cur_btc_price, price), amount)
        else:
            log.warning('Could not create buy order over {0} and there are no open sell orders, reset required'
                        .format(str(amount)))
            return False

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        # insufficient margin
        if "nsufficient" in str(error.args):
            log.error('Insufficient initial margin - not buying ' + str(amount))
            return False
        elif "too low" in str(error.args):
            log.error('Margin level too low - not buying ' + str(amount))
            return False
        log.error('Got an error ' + type(error).__name__ + str(error.args) + ', retrying in about 5 seconds...')
        sleep_for(4, 6)
        return create_buy_order(update_price(cur_btc_price, price), amount)


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
            if conf.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase', 'liquid']:
                new_order = exchange.create_market_sell_order(conf.pair, amount)
            elif conf.exchange == 'kraken':
                new_order = exchange.create_market_sell_order(conf.pair, amount_btc, {'leverage': 2})

            log.info('Created ' + str(new_order))
            order = Order(new_order)
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
            if conf.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase', 'liquid']:
                new_order = exchange.create_market_buy_order(conf.pair, amount)
            elif conf.exchange == 'kraken':
                new_order = exchange.create_market_buy_order(conf.pair, amount_btc, {'leverage': 2, 'oflags': 'fcib'})

            log.info('Created ' + str(new_order))
            order = Order(new_order)
            curr_buy_order = order

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
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
        if conf.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase', 'liquid']:
            return exchange.fetch_balance()['info'][0]['walletBalance'] * conf.satoshi_factor
        elif conf.exchange == 'kraken':
            return float(exchange.private_post_tradebalance()['result']['tb'])

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
        if conf.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase', 'liquid']:
            return exchange.private_get_position()[0]['currentQty']
        elif conf.exchange == 'kraken':
            result = exchange.private_post_tradebalance()['result']
            return round(float(result['e']) - float(result['mf']))

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        log.error('Got an error ' + type(error).__name__ + str(error.args) + ', retrying in about 5 seconds...')
        sleep_for(4, 6)
        return get_used_balance()


def get_position_info():
    """
    Fetch position information
    """
    try:
        if conf.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase', 'liquid']:
            response = exchange.private_get_position()
            if response:
                return response[0]
            return None
        elif conf.exchange == 'kraken':
            log.error("get_position_info() not yet implemented for kraken")
            return

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
    highest_buy_order = sorted(buy_orders, key=lambda order: order.price, reverse=True)[0]
    if highest_buy_order.price < market_price * (1 - conf.change * conf.spread_factor):
        lowest_sell_order = sorted(sell_orders, key=lambda order: order.price)[0]
        if lowest_sell_order.price > market_price * (1 + conf.change * conf.spread_factor):
            log.info("Orders above spread tolerance min sell: {0} max buy: {1} current rate: {2}".format(
                lowest_sell_order.price, highest_buy_order.price, market_price))
            log.info("Canceling highest buy order id: {0} price: {1} amount: {2}".format(
                highest_buy_order.id, highest_buy_order.price, highest_buy_order.amount))
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

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        log.error('Got an error' + type(error).__name__ + str(error.args) + ', retrying in about 5 seconds...')
        sleep_for(4, 6)
        return get_margin_balance()

    return bal


def calculate_used_margin_percentage(bal=None):
    """
    Calculates the used margin percentage
    """
    if bal is None:
        bal = get_margin_balance()
    return float(100 - (bal['free'] / bal['total']) * 100)


def get_avg_entry_price():
    """
    Fetches the average entry price of a position
    """
    try:
        avg = exchange.private_get_position()[0]['avgEntryPrice']

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        log.error('Got an error' + type(error).__name__ + str(error.args) + ', retrying in about 5 seconds...')
        sleep_for(4, 6)
        return get_avg_entry_price()

    if avg is not None:
        return avg
    return 0


def calc_avg_entry_price(open_orders):
    """"
    Calculates the average entry price of the remaining amount of all open orders (required for kraken only)
    """
    total_amount = 0
    total_price = 0
    if len(open_orders) > 0:
        for o in open_orders:
            total_amount += o['remaining']
            total_price += o['price'] * o['remaining']
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
        oos = OpenOrdersSummary(exchange.fetch_open_orders(conf.pair, since=None, limit=None, params={}))

        log.info("Used margin: {:>17.2f}%".format(calculate_used_margin_percentage()))
        if conf.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase', 'liquid']:
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

        if not oos.orders:
            log.info("No open orders")

        if oos.orders:
            log.info("Value of buy orders " + conf.base + ": {:>2}".format(int(oos.total_buy_order_value)))
            log.info("Value of sell orders " + conf.base + ": {:>1}".format(int(oos.total_sell_order_value)))
            log.info("No. of buy orders: {:>8}".format(len(oos.buy_orders)))
            log.info("No. of sell orders: {:>7}".format(len(oos.sell_orders)))
            log.info('-------------------------------')

            if not force_close and not auto_conf:
                init = input('There are open orders! Would you like to load them? (y/n) ')

            if not force_close and (auto_conf or init.lower() in ['y', 'yes']):
                if oos.sell_orders:
                    for o in oos.sell_orders:
                        sell_orders.append(o)
                    sell_price = sell_orders[0].price

                if oos.buy_orders:
                    for o in oos.buy_orders:
                        buy_orders.append(o)
                    curr_buy_order = buy_orders[0]
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

            else:
                log.info('Unrealised PNL: {0} BTC'.format(str(get_unrealised_pnl(conf.symbol) * conf.satoshi_factor)))
                cancel = ''
                if not force_close:
                    cancel = input('All existing orders will be canceled! Are you sure (y/n)? ')
                if force_close or cancel.lower() in ['y', 'yes']:
                    cancel_orders(oos.orders)

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
        return False


def cancel_orders(orders: [Order]):
    """
    Close a list of orders
    :param orders:
    """
    try:
        for o in orders:
            log.debug('cancel {0} order'.format(o['side']))

            status = exchange.fetch_order_status(o['id'])
            if status == 'open':
                exchange.cancel_order(o['id'])
            else:
                log.warning('Cancel {0} order {1} was in state '.format(str(o['side']), str(o['id'])) + status)

    except ccxt.OrderNotFound as error:
        log.error('Cancel {0} order {1} not found '.format(str(o['side']), str(o['id'])) + error.args)
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
        if conf.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase', 'liquid']:
            for p in exchange.private_get_position():
                if p['isOpen'] and p['symbol'] == symbol:
                    return p
        elif conf.exchange == 'kraken':
            a = exchange.private_post_openpositions()
            if a['result'] == 'success':
                for p in a['openPositions']:
                    if p['symbol'] == symbol:
                        return p
        return None

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        log.error('Got an error ' + type(error).__name__ + str(error.args) + ', retrying in about 5 seconds...')
        sleep_for(4, 6)
        return get_open_position(symbol)


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
    file = open(filename + '.pid', 'w')
    file.write(str(os.getpid()) + ' ' + filename)
    file.close()


def daily_report():
    """
    Creates a daily report email around 12:10 UTC
    """
    global email_sent

    if conf.send_emails:
        now = datetime.datetime.utcnow()
        if datetime.datetime(2012, 1, 17, 12, 15).time() > now.time() > datetime.datetime(2012, 1, 17, 12,
                                                                                          10).time() and email_sent != now.day:
            subject = "Daily report for {0}".format(conf.bot_instance)
            send_mail(subject, create_mail_content())
            email_sent = now.day


def create_mail_content():
    """
    Fetches the data required for the daily report email
    :return: mailcontent: str
    """
    try:
        oos = OpenOrdersSummary(exchange.fetch_open_orders(conf.pair, since=None, limit=None, params={}))

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        log.error('Got an error ' + type(error).__name__ + str(error.args) + ', retrying in about 5 seconds...')
        sleep_for(4, 6)
        return create_mail_content()

    content = []
    content.append("{0} {1} UTC".format(conf.bot_instance, datetime.datetime.utcnow()))
    content.append("Version: {:>21}".format(conf.bot_version))
    content.append("Difference: {:>18.5f}".format(conf.change))
    content.append("Divider: {:>21.2}".format(conf.divider))
    sleep_for(2, 4)
    bal = get_margin_balance()
    if conf.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase', 'liquid']:
        sleep_for(1, 2)
        poi = get_position_info()
        content.append("Liquidation price: {:>10.1f}".format(poi['liquidationPrice']))
        del poi
        content.append("Wallet balance " + conf.base + ": {:>12.4f}".format(get_wallet_balance()))
        content.append("Margin balance " + conf.base + ": {:>12.4f}".format(bal['total']))
    elif conf.exchange == 'kraken':
        content.append("Wallet balance " + conf.quote + ": {:>10.2f}".format(get_wallet_balance()))
        content.append("Margin balance " + conf.quote + ": {:>10.2f}".format(bal['total']))
    content.append("Used margin: {:>17.2f}%".format(calculate_used_margin_percentage(bal)))
    if conf.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase', 'liquid']:
        content.append("Leverage: {:>20.2f}x".format(get_margin_leverage()))
    elif conf.exchange == 'kraken':
        content.append("Leverage: {:>20.1f}%".format(get_margin_leverage()))
    sleep_for(4, 6)
    content.append("Position " + conf.quote + ": {:>15}".format(get_used_balance()))
    sleep_for(4, 6)
    content.append("Value of buy orders " + conf.quote + ": {:>4}".format(int(oos.total_buy_order_value)))
    content.append("Value of sell orders " + conf.quote + ": {:>1}".format(int(oos.total_sell_order_value)))
    content.append("No. of buy orders: {:>9}".format(len(oos.buy_orders)))
    content.append("No. of sell orders: {:>8}".format(len(oos.sell_orders)))
    content.append("No. of forced resets is: {:>3}".format(reset_counter))
    if auto_conf:
        content.append("Bot was resurrected at: {0} UTC".format(started))
    else:
        content.append("Bot running since: {0} UTC".format(started))
    del oos
    return '\n'.join(content) + '\n\n' + exchange.urls['www'] + '\n\n' + ';'.join(content).replace('  ', '').replace(
        ': ', ':;')


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


def __exit__(msg: str):
    log.info(msg + '\nBot will stop in 5s.')
    time.sleep(5)
    sys.exit()


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
    exchange = connect_to_exchange(conf)

    loop = init_orders(False, auto_conf)

    while True:
        market_price = get_current_price()
        amount = round(get_balance()['free'] / conf.divider * market_price)

        if loop:
            daily_report()
            trade_executed(market_price, amount)
            sell_executed(market_price, amount)
            if len(sell_orders) == 0:
                log.info('No sell orders, resetting all orders')
                loop = init_orders(True, False)
            else:
                spread(market_price)

        if not loop:
            # good enough as starting point if no compensation buy/sell is required
            curr_buy_order_size = amount
            compensate()
            loop = True

#
# V1.11.3
