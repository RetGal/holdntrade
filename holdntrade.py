#!/usr/bin/python
import configparser
import datetime
import inspect
import math
import logging
import os
import pickle
import random
import smtplib
import socket
import sys
import time
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from logging.handlers import RotatingFileHandler

import ccxt
import requests

# ------------------------------------------------------------------------------

SELL_PRICE = 0
SELL_ORDERS = []
BUY_PRICE = 0
BUY_ORDERS = []
CURR_BUY_ORDER = None
CURR_BUY_ORDER_SIZE = 0
RESET_COUNTER = 0
LOOP = False
AUTO_CONF = False
EMAIL_ONLY = False
EMAIL_SENT = 0
STARTED = datetime.datetime.utcnow().replace(microsecond=0)
STATS = None
HIBERNATE = False
INITIAL_LEVERAGE_SET = False
STOP_ERRORS = ['nsufficient', 'too low', 'not_enough_free_balance', 'margin_below']

# ------------------------------------------------------------------------------


class ExchangeConfig:
    """
    Holds the configuration read from separate .txt file.
    """
    def __init__(self):

        config = configparser.RawConfigParser()
        config.read(INSTANCE + ".txt")

        try:
            props = dict(config.items('config'))
            self.bot_instance = INSTANCE
            self.bot_version = "1.13.29"
            self.exchange = props['exchange'].strip('"').lower()
            self.api_key = props['api_key'].strip('"')
            self.api_secret = props['api_secret'].strip('"')
            self.test = bool(props['test'].strip('"').lower() == 'true')
            self.pair = props['pair'].strip('"')
            self.symbol = props['symbol'].strip('"')
            self.order_crypto_min = float(props['order_crypto_min'].strip('"'))
            self.satoshi_factor = 0.00000001
            self.change = abs(float(props['change'].strip('"')))
            self.quota = abs(int(props['quota'].strip('"')))
            if self.quota < 1:
                self.quota = 1
            self.spread_factor = abs(float(props['spread_factor'].strip('"')))
            self.auto_leverage = bool(props['auto_leverage'].strip('"').lower() == 'true')
            self.auto_leverage_escape = bool(props['auto_leverage_escape'].strip('"').lower() == 'true')
            self.leverage_default = abs(float(props['leverage_default'].strip('"')))
            self.leverage_low = abs(float(props['leverage_low'].strip('"')))
            self.leverage_high = abs(float(props['leverage_high'].strip('"')))
            self.leverage_escape = abs(float(props['leverage_escape'].strip('"')))
            self.mm_floor = abs(float(props['mm_floor'].strip('"')))
            self.mm_ceil = abs(float(props['mm_ceil'].strip('"')))
            self.mm_stop_buy = abs(float(props['mm_stop_buy'].strip('"')))
            currency = self.pair.split("/")
            self.base = currency[0]
            self.quote = currency[1]
            self.send_emails = bool(props['send_emails'].strip('"').lower() == 'true')
            self.recipient_addresses = props['recipient_addresses'].strip('"').replace(' ', '').split(",")
            self.sender_address = props['sender_address'].strip('"')
            self.sender_password = props['sender_password'].strip('"')
            self.mail_server = props['mail_server'].strip('"')
        except (configparser.NoSectionError, KeyError):
            raise SystemExit('invalid configuration for ' + INSTANCE)


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

        for oo in open_orders:
            o = Order(oo)
            self.orders.append(o)
            if o.side == 'sell':
                if CONF.exchange == 'kraken':
                    self.total_sell_order_value += o.amount * o.price
                else:
                    self.total_sell_order_value += o.amount
                self.sell_orders.append(o)
            elif o.side == 'buy':
                if CONF.exchange == 'kraken':
                    self.total_buy_order_value += o.amount * o.price
                else:
                    self.total_buy_order_value += o.amount
                self.buy_orders.append(o)
            else:
                LOG.error(inspect.stack()[1][3], ' ?!?')

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
        return "{} order id: {}, price: {}, amount: {}, created: {}".format(self.side, self.id, self.price,
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
        if existing is None:
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


def function_logger(console_level: int, log_filename: str, file_level: int = None):
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
        fh = RotatingFileHandler("{}.log".format(log_filename), mode='a', maxBytes=5 * 1024 * 1024, backupCount=4,
                                 encoding=None, delay=0)
        fh.setLevel(file_level)
        fh_format = logging.Formatter('%(asctime)s - %(lineno)4d - %(levelname)-8s - %(message)s')
        fh.setFormatter(fh_format)
        logger.addHandler(fh)

    return logger


def buy_executed():
    """
    Check if the most recent buy order has been executed.
    output: if the most recent buy order is still open,
    the output is print statements containing the amount were trying to buy for which price.
    Else if the order is closed, we follow with the followup function and createbuyorder and
    pass on the variables we got from input.
    """
    global CURR_BUY_ORDER_SIZE
    global BUY_ORDERS
    global HIBERNATE
    global INITIAL_LEVERAGE_SET

    status = fetch_order_status(CURR_BUY_ORDER.id) if CURR_BUY_ORDER is not None else 'suspect'
    LOG.debug('-------------------------------')
    LOG.debug(time.ctime())
    price = get_current_price()
    if status == 'open':
        LOG.debug('Open Buy Order! Amount: %d @ %.1f', int(CURR_BUY_ORDER_SIZE), float(BUY_PRICE))
        LOG.debug('Current Price: %.1f', price)
    elif status in ['closed', 'canceled']:
        LOG.info('Buy executed, starting follow up')
        # use amount of last (previous) buy order for next sell order
        last_buy_amount = CURR_BUY_ORDER_SIZE
        if CURR_BUY_ORDER in BUY_ORDERS:
            BUY_ORDERS.remove(CURR_BUY_ORDER)
        if not INITIAL_LEVERAGE_SET:
            INITIAL_LEVERAGE_SET = set_initial_leverage()
        mm = fetch_mayer()
        adjust_leverage(mm)
        HIBERNATE = shall_hibernate(mm)
        if not HIBERNATE:
            if create_buy_order(price, calculate_buy_order_amount()):
                create_sell_order(last_buy_amount)
            else:
                LOG.warning('Resetting')
                init_orders(True, False)
    else:
        LOG.warning('You should not be here, order state is %s', status)


def sell_executed():
    """
    Check if any of the open sell orders has been executed.
    output: loop through all open sell orders and check if one has been executed. If no, exit with print statement.
    Else if it has been executed, remove the order from the list of open orders,
    cancel it on Bitmex and create a new buy order.
    """
    global SELL_ORDERS
    global HIBERNATE

    for order in SELL_ORDERS:
        time.sleep(0.5)
        status = fetch_order_status(order.id)
        if status == 'open':
            LOG.debug('Sell still open')
        elif status in ['closed', 'canceled']:
            if order in SELL_ORDERS:
                SELL_ORDERS.remove(order)
            LOG.info('Sell executed')
            mm = fetch_mayer()
            adjust_leverage(mm)
            HIBERNATE = shall_hibernate(mm)
            if not HIBERNATE:
                if not SELL_ORDERS:
                    create_divided_sell_order()
                cancel_current_buy_order()
                price = get_current_price()
                if not create_buy_order(price, calculate_buy_order_amount()):
                    LOG.warning('Resetting')
                    init_orders(True, False)
        else:
            LOG.warning('You should not be here, order state: %s', status)


def shall_hibernate(mayer: dict = None):
    global HIBERNATE

    if mayer is None:
        mayer = fetch_mayer()
    if mayer is not None and mayer['current']:
        if mayer['current'] > CONF.mm_stop_buy:
            return True
        if CONF.auto_leverage_escape:
            return get_leverage() > CONF.leverage_escape
        return get_leverage() > get_target_leverage(mayer)
    return HIBERNATE


def cancel_current_buy_order():
    """
    Cancels the current buy order
    """
    global CURR_BUY_ORDER

    if CURR_BUY_ORDER is not None:
        cancel_order(CURR_BUY_ORDER)
        if CURR_BUY_ORDER in BUY_ORDERS:
            BUY_ORDERS.remove(CURR_BUY_ORDER)
        LOG.info('Canceled current %s', str(CURR_BUY_ORDER))
        CURR_BUY_ORDER = None if not BUY_ORDERS else BUY_ORDERS[0]


def create_first_sell_order():
    global SELL_PRICE

    SELL_PRICE = round(get_current_price() * (1 + CONF.change))
    available = get_position_balance()
    LOG.info("Creating first sell order")
    create_sell_order(round(available / CONF.quota))


def create_first_buy_order():
    global HIBERNATE

    mm = fetch_mayer()
    adjust_leverage(mm)
    HIBERNATE = shall_hibernate(mm)
    if not HIBERNATE:
        LOG.info("Creating first buy order")
        create_buy_order(get_current_price(), calculate_buy_order_amount())


def create_sell_order(fixed_order_size: int = None):
    """
    Loop that starts after buy order is executed and sends sell order to exchange
    as well as appends the orderID to the sell_orders list.
    """
    global SELL_PRICE
    global CURR_BUY_ORDER_SIZE
    global SELL_ORDERS

    order_size = CURR_BUY_ORDER_SIZE if fixed_order_size is None else fixed_order_size

    available = get_balance()['free'] * SELL_PRICE
    if available < order_size:
        # sold out - the main loop will re-init if there are no other sell orders open
        LOG.warning('Not executing sell order over %d (only %d left)', order_size, available)
        return

    try:
        if not is_order_below_limit(order_size, SELL_PRICE):
            if CONF.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase']:
                new_order = EXCHANGE.create_limit_sell_order(CONF.pair, order_size, SELL_PRICE)
            elif CONF.exchange == 'kraken':
                rate = get_current_price()
                new_order = EXCHANGE.create_limit_sell_order(CONF.pair, to_crypto_amount(order_size, rate), SELL_PRICE,
                                                             {'leverage': CONF.leverage_default})
            elif CONF.exchange == 'liquid':
                rate = get_current_price()
                new_order = EXCHANGE.create_limit_sell_order(CONF.pair, to_crypto_amount(order_size, rate), SELL_PRICE,
                                                             {'leverage_level': CONF.leverage_default,
                                                              'funding_currency': CONF.base})
            order = Order(new_order)
            SELL_ORDERS.append(order)
            LOG.info('Created %s', str(order))

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        if any(e in str(error.args) for e in STOP_ERRORS):
            LOG.error('Insufficient funds - not selling %d', order_size)
            return
        LOG.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        SELL_PRICE = round(get_current_price() * (1 + CONF.change))
        return create_sell_order(fixed_order_size)


def create_divided_sell_order():
    """
    Loop that starts after buy order is executed and sends sell order to exchange
    as well as appends the orderID to the sell_orders list.
    """
    global SELL_ORDERS
    global SELL_PRICE

    try:
        available = get_position_balance()
        amount = round(available / CONF.quota)

        if not is_order_below_limit(amount, SELL_PRICE):
            if CONF.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase', 'liquid']:
                new_order = EXCHANGE.create_limit_sell_order(CONF.pair, amount, SELL_PRICE)
            elif CONF.exchange == 'kraken':
                rate = get_current_price()
                new_order = EXCHANGE.create_limit_sell_order(CONF.pair, to_crypto_amount(amount, rate), SELL_PRICE,
                                                             {'leverage': CONF.leverage_default})
            elif CONF.exchange == 'liquid':
                rate = get_current_price()
                new_order = EXCHANGE.create_limit_sell_order(CONF.pair, to_crypto_amount(amount, rate), SELL_PRICE,
                                                             {'leverage_level': CONF.leverage_default,
                                                              'funding_currency': CONF.base})
            order = Order(new_order)
            SELL_ORDERS.append(order)
            LOG.info('Created %s', str(order))

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        if any(e in str(error.args) for e in STOP_ERRORS):
            LOG.error('Insufficient funds - not selling %d', amount)
            return
        LOG.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        SELL_PRICE = round(get_current_price() * (1 + CONF.change))
        return create_divided_sell_order()


def fetch_order_status(order_id: str):
    """
    Fetches the status of an order
    input: id of an order
    output: status of the order (open, closed)
    """
    try:
        return EXCHANGE.fetch_order_status(order_id)

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        LOG.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return fetch_order_status(order_id)


def cancel_order(order: Order):
    """
    Cancels an order
    """
    try:
        if order is not None:
            status = EXCHANGE.fetch_order_status(order.id)
            if status == 'open':
                EXCHANGE.cancel_order(order.id)
            else:
                LOG.warning('Order to be canceled %s was in state %s', order.id, status)

    except ccxt.OrderNotFound as error:
        LOG.error('Order to be canceled not found %s %s', order.id, str(error.args))
        return
    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        LOG.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return cancel_order(order)


def create_buy_order(price: float, buy_amount: int):
    """
    Creates a buy order and sets the values as global ones. Used by other functions.
    :param price current price of crypto
    :param buy_amount the order volume
    output: calculate the price to get long (price + change) and to get short (price - change).
    In addition set the current orderID and current order size as global values.
    If the amount is below the order limit or there is not enough margin and there are open sell orders, the function
    is going to sleep, allowing sell orders to be filled - afterwards the amount is recalculated and the function calls
    itself with the new amount
    """
    global SELL_PRICE
    global BUY_PRICE
    global CURR_BUY_ORDER_SIZE
    global CURR_BUY_ORDER
    global BUY_ORDERS

    BUY_PRICE = round(price * (1 - CONF.change))
    SELL_PRICE = round(price * (1 + CONF.change))
    CURR_BUY_ORDER_SIZE = buy_amount
    curr_price = get_current_price()

    try:
        if not is_order_below_limit(buy_amount, BUY_PRICE):
            if CONF.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase']:
                new_order = EXCHANGE.create_limit_buy_order(CONF.pair, buy_amount, BUY_PRICE)
            elif CONF.exchange == 'kraken':
                new_order = EXCHANGE.create_limit_buy_order(CONF.pair, to_crypto_amount(buy_amount, curr_price), BUY_PRICE,
                                                            {'leverage': CONF.leverage_default, 'oflags': 'fcib'})
            elif CONF.exchange == 'liquid':
                new_order = EXCHANGE.create_limit_buy_order(CONF.pair, to_crypto_amount(buy_amount, curr_price), BUY_PRICE,
                                                            {'leverage_level': CONF.leverage_default,
                                                             'funding_currency': CONF.base})
            order = Order(new_order)
            LOG.info('Created %s', str(order))
            CURR_BUY_ORDER = order
            BUY_ORDERS.append(order)
            return True
        if SELL_ORDERS:
            LOG.info('Could not create buy order, waiting for a sell order to be realised')
            return delay_buy_order(curr_price, price)

        LOG.warning('Could not create buy order over %d and there are no open sell orders, reset required', buy_amount)
        return False

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        if any(e in str(error.args) for e in STOP_ERRORS):
            if SELL_ORDERS:
                LOG.info(
                    'Could not create buy order over %s, insufficient margin, waiting for a sell order to be realised',
                    str(buy_amount))
                return delay_buy_order(curr_price, price)

            LOG.warning('Could not create buy order over %d, insufficient margin', buy_amount)
            return False
        LOG.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return create_buy_order(update_price(curr_price, price), buy_amount)


def delay_buy_order(crypto_price: float, price: float):
    """
    Delays the creation of a buy order, allowing sell orders to be filled - afterwards the amount is recalculated and
    the function calls create_buy_order with the current price and the new amount
    :param crypto_price: the crypto rate with which price was calculated
    :param price: the price of the original buy order to be created
    """
    sleep_for(90, 180)
    daily_report()
    new_amount = round(get_balance()['free'] / CONF.quota * get_current_price())  # recalculate order size
    if is_order_below_limit(new_amount, update_price(crypto_price, price)):
        if CONF.auto_leverage and CONF.auto_leverage_escape:
            boost_leverage()
        elif CONF.auto_leverage:
            mm = fetch_mayer()
            adjust_leverage(mm)
    return create_buy_order(update_price(crypto_price, price), calculate_buy_order_amount())


def calculate_buy_order_amount():
    """
    Calculates the buy order amount.
    :return: amount to be bought in fiat
    """
    available = get_position_balance()
    if available < 0:
        return 0
    return round(available / CONF.quota)


def create_market_sell_order(amount_crypto: float):
    """
    Creates a market sell order and sets the values as global ones. Used to compensate margins above 50%.
    input: amount_crypto to be sold to reach 50% margin
    """
    global BUY_PRICE
    global SELL_PRICE
    global SELL_ORDERS

    cur_price = get_current_price()
    amount_fiat = round(amount_crypto * cur_price)
    BUY_PRICE = round(cur_price * (1 - CONF.change))
    SELL_PRICE = round(cur_price * (1 + CONF.change))

    try:
        if not is_crypto_amount_below_limit(amount_crypto):
            if CONF.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase']:
                new_order = EXCHANGE.create_market_sell_order(CONF.pair, amount_fiat)
            elif CONF.exchange == 'kraken':
                new_order = EXCHANGE.create_market_sell_order(CONF.pair, amount_crypto, {'leverage': CONF.leverage_default})
            elif CONF.exchange == 'liquid':
                new_order = EXCHANGE.create_market_sell_order(CONF.pair, amount_fiat,
                                                              {'leverage_level': CONF.leverage_default})
            order = Order(new_order)
            LOG.info('Created market %s', str(order))
            SELL_ORDERS.append(order)

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        if any(e in str(error.args) for e in STOP_ERRORS):
            LOG.error('Insufficient balance/funds - not selling %d', amount_fiat)
            return
        LOG.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return create_market_sell_order(amount_crypto)


def create_market_buy_order(amount_crypto: float):
    """
    Creates a market buy order and sets the values as global ones. Used to compensate margins below 50%.
    input: amount_crypto to be bought to reach 50% margin
    """
    global BUY_PRICE
    global SELL_PRICE
    global CURR_BUY_ORDER

    cur_price = get_current_price()
    amount_fiat = round(amount_crypto * cur_price)
    BUY_PRICE = round(cur_price * (1 - CONF.change))
    SELL_PRICE = round(cur_price * (1 + CONF.change))

    try:
        if not is_order_below_limit(amount_fiat, cur_price):
            if CONF.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase']:
                new_order = EXCHANGE.create_market_buy_order(CONF.pair, amount_fiat)
            elif CONF.exchange == 'kraken':
                new_order = EXCHANGE.create_market_buy_order(CONF.pair, amount_crypto,
                                                             {'leverage': CONF.leverage_default, 'oflags': 'fcib'})
            elif CONF.exchange == 'liquid':
                new_order = EXCHANGE.create_market_buy_order(CONF.pair, amount_crypto,
                                                             {'leverage_level': CONF.leverage_default,
                                                              'funding_currency': CONF.base})
            order = Order(new_order)
            LOG.info('Created market %s', str(order))
            CURR_BUY_ORDER = None

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        if "not_enough_free" or "free_margin_below" in str(error.args):
            LOG.error('Not enough free margin/balance %s %s', type(error).__name__, str(error.args))
            return

        LOG.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return create_market_buy_order(amount_crypto)


def get_margin_leverage():
    """
    Fetch the leverage
    """
    try:
        if CONF.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase']:
            return EXCHANGE.fetch_balance()['info'][0]['marginLeverage']
        if CONF.exchange == 'kraken':
            return float(EXCHANGE.private_post_tradebalance()['result']['ml'])
        if CONF.exchange == 'liquid':
            # TODO poi = get_position_info()
            LOG.error("get_margin_leverage() not yet implemented for %s", CONF.exchange)
            return None

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        LOG.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return get_margin_leverage()


def get_relevant_leverage():
    """
    Returns the higher of the two leverages - used to set the initial leverage
    """
    position_leverage = get_leverage()
    margin_leverage = get_margin_leverage()
    if position_leverage is None:
        return margin_leverage
    if margin_leverage is None:
        return position_leverage
    # a position leverage of 100 means cross (bitmex)
    return position_leverage if 100 > position_leverage > margin_leverage else margin_leverage


def get_wallet_balance():
    """
    Fetch the wallet balance in crypto
    """
    try:
        if CONF.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase']:
            return EXCHANGE.fetch_balance()['info'][0]['walletBalance'] * CONF.satoshi_factor
        if CONF.exchange == 'kraken':
            asset = CONF.base if CONF.base != 'BTC' else 'XBt'
            return float(EXCHANGE.private_post_tradebalance({'asset': asset})['result']['tb'])
        if CONF.exchange == 'liquid':
            result = EXCHANGE.private_get_accounts_balance()
            if result is not None:
                for b in result:
                    if b['currency'] == CONF.base:
                        return float(b['balance'])

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        LOG.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return get_wallet_balance()


def get_balance():
    """
    Fetch the balance in crypto.
    output: balance (used,free,total) in crypto
    """
    try:
        if CONF.exchange != 'liquid':
            bal = EXCHANGE.fetch_balance()[CONF.base]
            if bal['used'] is None:
                bal['used'] = 0
            if bal['free'] is None:
                bal['free'] = 0
            return bal

        bal = None
        result = EXCHANGE.private_get_trading_accounts()
        if result is not None:
            for acc in result:
                if acc['currency_pair_code'] == CONF.symbol and float(acc['margin']) > 0:
                    bal = {'used': float(acc['margin']), 'free': float(acc['free_margin']),
                           'total': float(acc['equity'])}
        if bal is None:
            # no position => return wallet balance
            result = EXCHANGE.private_get_accounts_balance()
            if result is not None:
                for b in result:
                    if b['currency'] == CONF.base:
                        bal = {'used': 0, 'free': float(b['balance']), 'total': float(b['balance'])}
        return bal

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        LOG.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return get_balance()


def get_position_balance():
    """
    Fetch the position balance in fiat.
    output: balance
    """
    try:
        if CONF.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase']:
            return EXCHANGE.private_get_position()[0]['currentQty']
        if CONF.exchange == 'kraken':
            result = EXCHANGE.private_post_tradebalance()['result']
            return round(float(result['e']) - float(result['mf']))
        if CONF.exchange == 'liquid':
            return round(get_balance()['used'] * get_current_price())

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        LOG.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return get_position_balance()


def get_net_deposits():
    """
    Get deposits and withdraws to calculate the net deposits in crypto.
    return: net deposits
    """
    try:
        currency = CONF.base if CONF.base != 'BTC' else 'XBt'
        if CONF.exchange == 'bitmex':
            result = EXCHANGE.private_get_user_wallet({'currency': currency})
            return (result['deposited'] - result['withdrawn']) * CONF.satoshi_factor
        if CONF.exchange == 'kraken':
            net_deposits = 0
            deposits = EXCHANGE.fetch_deposits(CONF.base)
            for deposit in deposits:
                net_deposits += deposit['amount']
            ledgers = EXCHANGE.private_post_ledgers({'asset': currency, 'type': 'withdrawal'})['result']['ledger']
            for withdrawal_id in ledgers:
                net_deposits += float(ledgers[withdrawal_id]['amount'])
            return net_deposits
        LOG.error("get_net_deposit() not yet implemented for %s", CONF.exchange)
        return None

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        LOG.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return get_net_deposits()


def get_position_info():
    """
    Fetch position information
    """
    try:
        if CONF.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase']:
            response = EXCHANGE.private_get_position()
            if response and response[0] and response[0]['avgEntryPrice']:
                return response[0]
            return None
        if CONF.exchange == 'kraken':
            LOG.error("get_position_info() not yet implemented for kraken")
            return None
        if CONF.exchange == 'liquid':
            response = EXCHANGE.private_get_trading_accounts()
            for pos in response:
                if pos['currency_pair_code'] == CONF.symbol and pos['funding_currency'] == CONF.base and \
                        float(pos['margin']) > 0:
                    return pos
            return None

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        LOG.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return get_position_info()


def get_interest_rate():
    """
    Fetches and converts the interest rate
    """
    try:
        if CONF.exchange == 'bitmex':
            today = datetime.date.today().isoformat()
            result = EXCHANGE.public_get_funding({'symbol': CONF.symbol, 'startTime': today, 'count': 1})
            if result is not None:
                return result[0]['fundingRateDaily'] * -100
            return None
        LOG.error("get_interest_rate() not yet implemented for %s", CONF.exchange)

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        LOG.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return get_interest_rate()


def compensate():
    """
    Approaches the margin used towards 50% by selling or buying the difference to market price
    """
    if CONF.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase', 'liquid']:
        bal = get_balance()
    elif CONF.exchange == 'kraken':
        bal = get_margin_balance()

    used = float(100 - (bal['free'] / bal['total']) * 100)
    if used < 40 or used > 60:
        amount_crypto = float(bal['total'] / 2 - bal['used'])
        if amount_crypto > 0:
            LOG.info("Need to buy {} {} in order to reach 50% margin".format(amount_crypto, CONF.base))
            create_market_buy_order(amount_crypto)
        else:
            LOG.info("Need to sell {} {} in order to reach 50% margin".format(abs(amount_crypto), CONF.base))
            create_market_sell_order(abs(amount_crypto))


def spread(price: float):
    """
    Checks if the difference between the highest buy order price and the market price is bigger than spread_factor times
    change and the difference of the lowest sell order to the market price is bigger spread_factor times change
    If so, then the highest buy order is canceled and a new buy and sell order are created with the configured offset
    to the market price
    """
    if BUY_ORDERS and SELL_ORDERS:
        highest_buy_order = sorted(BUY_ORDERS, key=lambda order: order.price, reverse=True)[0]
        if highest_buy_order.price < price * (1 - CONF.change * CONF.spread_factor):
            lowest_sell_order = sorted(SELL_ORDERS, key=lambda order: order.price)[0]
            if lowest_sell_order.price > price * (1 + CONF.change * CONF.spread_factor):
                LOG.info("Orders above spread tolerance min sell: %f max buy: %f current rate: %f",
                         lowest_sell_order.price, highest_buy_order.price, price)
                LOG.info("Canceling highest %s", str(highest_buy_order))
                cancel_order(highest_buy_order)
                BUY_ORDERS.remove(highest_buy_order)
                if create_buy_order(price, highest_buy_order.amount):
                    create_sell_order()


def get_margin_balance():
    """
    Fetches the margin balance in fiat (free and total)
    return: balance in fiat
    """
    try:
        if CONF.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase']:
            bal = EXCHANGE.fetch_balance()[CONF.base]
        elif CONF.exchange == 'kraken':
            bal = EXCHANGE.private_post_tradebalance({'asset': CONF.base})['result']
            bal['free'] = float(bal['mf'])
            bal['total'] = float(bal['e'])
            bal['used'] = float(bal['m'])
        elif CONF.exchange == 'liquid':
            bal = get_balance()
        return bal

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        LOG.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
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


def calculate_avg_entry_price_and_total_quantity(open_orders: [Order]):
    """"
    Calculates the average price and the quantity of the remaining amount of all open orders
    :param open_orders: [Order]
    """
    total_amount = 0
    total_price = 0
    for o in open_orders:
        total_amount += o.amount
        total_price += o.price * o.amount
    if total_amount > 0:
        return {'avg':  total_price / total_amount, 'qty': total_amount}
    return {'avg': 0, 'qty': 0}


def get_current_price():
    """
    Fetch the current crypto price
    output: last bid price
    """
    try:
        return EXCHANGE.fetch_ticker(CONF.pair)['bid']

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        LOG.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sleep_for(4, 6)
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
    :return: False if compensate is required, True if not
    """
    global SELL_PRICE
    global SELL_ORDERS
    global CURR_BUY_ORDER_SIZE
    global CURR_BUY_ORDER
    global BUY_ORDERS
    global BUY_PRICE
    global RESET_COUNTER

    if force_close:
        RESET_COUNTER += 1

    try:
        init = ''
        if auto_conf:
            LOG.warning("Bot was resurrected by hades")

        # Handle open orders
        oos = get_open_orders()

        # deactivate bot instance
        if oos is None:
            os.remove(INSTANCE + '.pid')
            text = "Deactivated {}".format(CONF.bot_instance)
            LOG.error(text)
            send_mail(text, text)
            exit(1)

        LOG.info("Used margin: {:>17.2f}%".format(calculate_used_margin_percentage()))
        print_position_info(oos)

        if oos.orders:
            LOG.info("Value of buy orders {}: {:>2}".format(CONF.quote, int(oos.total_buy_order_value)))
            LOG.info("Value of sell orders {}: {:>1}".format(CONF.quote, int(oos.total_sell_order_value)))
            LOG.info("No. of buy orders: {:>8}".format(len(oos.buy_orders)))
            LOG.info("No. of sell orders: {:>7}".format(len(oos.sell_orders)))
            LOG.info('-------------------------------')

            if not force_close and not auto_conf:
                init = input('There are open orders! Would you like to load them? (y/n) ')
            if not force_close and (auto_conf or init.lower() in ['y', 'yes']):
                return load_existing_orders(oos)

            LOG.info('Unrealised PNL: %s %s', str(get_unrealised_pnl(CONF.symbol) * CONF.satoshi_factor), CONF.base)
            if force_close:
                cancel_orders(oos.orders)
            else:
                clear_position = input('There is an open ' + CONF.base + ' position! Would you like to close it? (y/n) ')
                if clear_position.lower() in ['y', 'yes']:
                    cancel_orders(oos.orders)
                    close_position(CONF.symbol)
                else:
                    compensate_position = input('Would you like to compensate to 50%? (y/n) ')
                    if compensate_position.lower() in ['n', 'no']:
                        # No "compensate" wanted
                        return True

        # Handle open positions if no orders are open
        elif not force_close and not auto_conf and get_open_position(CONF.symbol) is not None:
            msg = 'There is an open ' + CONF.base + ' position!\nUnrealised PNL: {:.8f} ' + CONF.base + \
                  '\nWould you like to close it? (y/n) '
            init = input(msg.format(get_unrealised_pnl(CONF.symbol) * CONF.satoshi_factor))
            if init.lower() in ['y', 'yes']:
                close_position(CONF.symbol)

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        LOG.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return init_orders(force_close, auto_conf)

    else:
        del oos
        # compensate
        return False


def load_existing_orders(oos: OpenOrdersSummary):
    global SELL_ORDERS, SELL_PRICE, BUY_ORDERS, CURR_BUY_ORDER, BUY_PRICE, CURR_BUY_ORDER_SIZE
    if oos.sell_orders:
        SELL_ORDERS = oos.sell_orders
        SELL_PRICE = SELL_ORDERS[-1].price  # lowest if several
    if oos.buy_orders:
        BUY_ORDERS = oos.buy_orders
        CURR_BUY_ORDER = BUY_ORDERS[0]  # highest if several
        BUY_PRICE = CURR_BUY_ORDER.price
        CURR_BUY_ORDER_SIZE = CURR_BUY_ORDER.amount
    # All sell orders executed
    if not oos.sell_orders:
        create_first_sell_order()
    # All buy orders executed
    elif not oos.buy_orders:
        create_first_buy_order()
    del oos
    LOG.info('Initialization complete (using existing orders)')
    # No "compensate" necessary
    return True


def cancel_orders(orders: [Order]):
    """
    Close a list of orders
    :param orders: [Order]
    """
    try:
        for o in orders:
            LOG.debug('Cancel %s', str(o))
            status = EXCHANGE.fetch_order_status(o.id)
            if status == 'open':
                EXCHANGE.cancel_order(o.id)
            else:
                LOG.warning('Cancel %s was in state %s', str(o), status)

    except ccxt.OrderNotFound as error:
        LOG.error('Cancel %s not found : %s', str(o), str(error.args))
        return
    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        LOG.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return cancel_orders(orders)


def close_position(symbol: str):
    """
    Close any open position
    """
    try:
        LOG.info('close position %s', symbol)
        if CONF.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase']:
            EXCHANGE.private_post_order_closeposition({'symbol': symbol})
        elif CONF.exchange == 'kraken':
            EXCHANGE.create_market_sell_order(CONF.pair, 0.0, {'leverage': CONF.leverage_default})
        elif CONF.exchange == 'liquid':
            EXCHANGE.private_put_trades_close_all()

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        # no retry in case of "no volume to close position" (kraken specific error)
        if "volume to close position" in str(error.args):
            return
        LOG.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return close_position(symbol)


def get_open_position(symbol: str):
    """
    Get all open positions
    :return: positions
    """
    try:
        if CONF.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase']:
            for p in EXCHANGE.private_get_position():
                if p['isOpen'] and p['symbol'] == symbol:
                    return p
        elif CONF.exchange == 'kraken':
            a = EXCHANGE.private_post_openpositions()
            if a['result'] == 'success':
                for p in a['openPositions']:
                    if p['symbol'] == symbol:
                        return p
        elif CONF.exchange == 'liquid':
            trades = EXCHANGE.private_get_trades({'status': 'open'})
            for model in trades['models']:
                if model['currency_pair_code'] == CONF.pair:
                    return model
        return None

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        LOG.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return get_open_position(symbol)


def get_open_orders(tries: int = 0):
    """
    Gets all open orders
    :return: OpenOrdersSummary
    """
    try:
        return OpenOrdersSummary(EXCHANGE.fetch_open_orders(CONF.pair, since=None, limit=None, params={}))

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        if "key is disabled" in str(error.args):
            LOG.warning('Key is disabled')
            return None
        LOG.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sleep_for(4, 6)
        if tries < 20000:
            return get_open_orders(tries+1)
        return None


def get_unrealised_pnl(symbol: str):
    """
    Returns the unrealised pnl for the requested currency
    :param symbol:
    :return: float
    """
    try:
        if get_open_position(symbol) is not None:
            return float(get_open_position(symbol)['unrealisedPnl'])
        return 0.0

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        LOG.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return get_unrealised_pnl(symbol)


def print_position_info(oos: OpenOrdersSummary):
    if CONF.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase']:
        sleep_for(1, 2)
        poi = get_position_info()
        if poi:
            LOG.info("Position {}: {:>13}".format(CONF.quote, poi['currentQty']))
            LOG.info("Entry price: {:>16.1f}".format(poi['avgEntryPrice']))
            LOG.info("Market price: {:>15.1f}".format(poi['markPrice']))
            LOG.info("Liquidation price: {:>10.1f}".format(poi['liquidationPrice']))
            del poi
        else:
            LOG.info("Available balance is {}: {:>3} ".format(CONF.base, get_balance()['free']))
            LOG.info("No position found, I will create one for you")
            return False
    elif CONF.exchange == 'kraken':
        LOG.info("Position {}: {:>13}".format(CONF.quote, get_position_balance()))
        LOG.info("Entry price: {:>16.1f}".format(calculate_avg_entry_price_and_total_quantity(oos.orders)['avg']))
        LOG.info("Market price: {:>15.1f}".format(get_current_price()))
    elif CONF.exchange == 'liquid':
        poi = get_position_info()
        if float(poi['position']) > 0:
            LOG.info("Position {}: {:>13.2f}".format(CONF.base, float(poi['position'])))
        else:
            LOG.info("Available balance is {}: {:>3} ".format(CONF.base, get_balance()['free']))
            LOG.info("No position found, I will create one for you")
            return False
    if not oos.orders:
        LOG.info("No open orders")


def connect_to_exchange():
    """
    Connects to the exchange.
    :return: exchange
    """
    exchanges = {'binance': ccxt.binance,
                 'bitfinex': ccxt.bitfinex,
                 'bitmex': ccxt.bitmex,
                 'coinbase': ccxt.coinbase,
                 'kraken': ccxt.kraken,
                 'liquid': ccxt.liquid}

    exchange = exchanges[CONF.exchange]({
        'enableRateLimit': True,
        'apiKey': CONF.api_key,
        'secret': CONF.api_secret,
        # 'verbose': True,
    })

    #pprint(dir(exchange))

    if hasattr(CONF, 'test') & CONF.test:
        if 'test' in exchange.urls:
            exchange.urls['api'] = exchange.urls['test']
        else:
            raise SystemExit('Test not supported by %s', CONF.exchange)

    LOG.info('Connecting to %s', CONF.exchange)
    return exchange


def sleep_for(greater: int, less: int):
    seconds = round(random.uniform(greater, less), 3)
    time.sleep(seconds)


def is_order_below_limit(order_amount: int, price: float):
    return is_crypto_amount_below_limit(abs(order_amount / price))


def is_crypto_amount_below_limit(crypto_amount: float):
    if abs(crypto_amount) < CONF.order_crypto_min:
        LOG.info('Per order volume below limit: %f', abs(crypto_amount))
        return True
    return False


def to_crypto_amount(fiat_amount: int, price: float):
    return round(fiat_amount / price, 8)


def write_control_file():
    with open(INSTANCE + '.pid', 'w') as f:
        f.write(str(os.getpid()) + ' ' + INSTANCE)


def daily_report(immediately: bool = False):
    """
    Creates a daily report email around 12:10 UTC or immediately if told to do so
    It also triggers the creation of the daily stats, which will be persisted
    """
    global EMAIL_SENT

    if CONF.send_emails:
        now = datetime.datetime.utcnow()
        if (immediately and datetime.datetime(2012, 1, 17, 12, 30).time() < now.time()) \
                or datetime.datetime(2012, 1, 17, 12, 30).time() > now.time() \
                > datetime.datetime(2012, 1, 17, 12, 10).time() and EMAIL_SENT != now.day:
            subject = "Daily report for {}".format(CONF.bot_instance)
            content = create_mail_content()
            filename_csv = CONF.bot_instance + '.csv'
            write_csv(content['csv'], filename_csv)
            send_mail(subject, content['text'], filename_csv)
            EMAIL_SENT = now.day


def create_mail_content():
    """
    Fetches and formats the data required for the daily report email
    :return: dict: text: str, csv: str
    """
    performance_part = create_report_part_performance()
    advice_part = create_report_part_advice()
    settings_part = create_report_part_settings()
    general_part = create_mail_part_general()

    performance = ["Performance", "-----------", '\n'.join(performance_part['mail']) + '\n* (change within 24 hours, 48 hours)', '\n\n']
    advice = ["Assessment / advice", "-------------------", '\n'.join(advice_part['mail']), '\n\n']
    settings = ["Your settings", "-------------", '\n'.join(settings_part['mail']), '\n\n']
    general = ["General", "-------", '\n'.join(general_part), '\n\n']

    bcs_url = 'https://bitcoin-schweiz.ch/bot/'
    explanation = 'Erläuterungen zu diesem Rapport: https://bitcoin-schweiz.ch/wp-content/uploads/2019/07/Tagesrapport.pdf'
    text = '\n'.join(performance) + '\n'.join(advice) + '\n'.join(settings) + '\n'.join(general) + bcs_url + '\n\n' + explanation + '\n'

    csv = CONF.bot_instance + ';' + str(datetime.datetime.utcnow().replace(microsecond=0)) + ' UTC;' + (';'.join(performance_part['csv']) + ';' + ';'.join(
        advice_part['csv']) + ';' + ';'.join(settings_part['csv']) + '\n')

    return {'text': text, 'csv': csv}


def create_report_part_settings():
    return {'mail': ["Rate change: {:>22.1f}%".format(CONF.change * 100),
                     "Quota: {:>28}".format('1/' + str(CONF.quota)),
                     "Spread factor: {:>20}".format(str(CONF.spread_factor)),
                     "Leverage default: {:>17}x".format(str(CONF.leverage_default)),
                     "Auto leverage: {:>20}".format(str('Y' if CONF.auto_leverage is True else 'N')),
                     "Auto leverage escape: {:>13}".format(str('Y' if CONF.auto_leverage_escape is True else 'N')),
                     "Leverage low: {:>21}x".format(str(CONF.leverage_low)),
                     "Leverage high: {:>20}x".format(str(CONF.leverage_high)),
                     "Leverage escape: {:>18}x".format(str(CONF.leverage_high)),
                     "Mayer multiple floor: {:>13}".format(str(CONF.mm_floor)),
                     "Mayer multiple ceil: {:>14}".format(str(CONF.mm_ceil)),
                     "Mayer multiple stop buy: {:>10}".format(str(CONF.mm_stop_buy))],
            'csv': ["Rate change:; {:.1f}%".format(float(CONF.change * 100)),
                    "Quota:; {:.3f}".format(1 / CONF.quota),
                    "Spread factor:; {}".format(str(CONF.spread_factor)),
                    "Leverage default:; {}".format(str(CONF.leverage_default)),
                    "Auto leverage:; {}".format(str('Y' if CONF.auto_leverage is True else 'N')),
                    "Auto leverage escape: {}".format(str('Y' if CONF.auto_leverage_escape is True else 'N')),
                    "Leverage low:; {}".format(str(CONF.leverage_low)),
                    "Leverage high:; {}".format(str(CONF.leverage_high)),
                    "Leverage escape:; {}".format(str(CONF.leverage_escape)),
                    "Mayer multiple floor:; {}".format(str(CONF.mm_floor)),
                    "Mayer multiple ceil:; {}".format(str(CONF.mm_ceil)),
                    "Mayer multiple stop buy:; {}".format(str(CONF.mm_stop_buy))]}


def create_mail_part_general():
    general = ["Generated: {:>28}".format(str(datetime.datetime.utcnow().replace(microsecond=0)) + " UTC")]
    if AUTO_CONF:
        general.append("Resurrected at: {:>18} UTC".format(str(STARTED)))
    else:
        general.append("Running since: {:>20} UTC".format(str(STARTED)))
    general.append("No. of resets: {:>20}".format(RESET_COUNTER))
    general.append("Bot: {:>30}".format(CONF.bot_instance + '@' + socket.gethostname()))
    general.append("Version: {:>26}".format(CONF.bot_version))
    return general


def create_report_part_advice():
    moving_average = read_moving_average()
    if moving_average is not None:
        padding = 6 + len(moving_average)
        part = {'mail': ["Moving average 144d/21d: {:>{}}".format(moving_average, padding)],
                'csv': ["Moving average 144d/21d:; {}".format(moving_average)]}
    else:
        part = {'mail': ["Moving average 144d/21d: {:>10}".format('n/a')],
                'csv': ["Moving average 144d/21d:; {}".format('n/a')]}
    append_mayer(part)
    return part


def create_report_part_performance():
    part = {'mail': [], 'csv': []}
    margin_balance = get_margin_balance()
    net_deposits = get_net_deposits()
    sleep_for(0, 1)
    append_performance(part, margin_balance['total'], net_deposits)
    poi = get_position_info()
    wallet_balance = get_wallet_balance()
    sleep_for(0, 1)
    oos = get_open_orders()
    # all_sold_balance = calculate_all_sold_balance(poi, oos.sell_orders, wallet_balance, margin_balance['total'], net_deposits)
    append_balances(part, margin_balance, poi, wallet_balance, None)
    append_orders(part, oos)
    append_interest_rate(part)
    return part


def append_orders(part: dict, oos: OpenOrdersSummary):
    """
    Appends order statistics
    """
    part['mail'].append("Value of buy orders " + CONF.quote + ": {:>10}".format(int(oos.total_buy_order_value)))
    part['mail'].append("Value of sell orders " + CONF.quote + ": {:>9}".format(int(oos.total_sell_order_value)))
    part['mail'].append("No. of buy orders: {:>16}".format(len(oos.buy_orders)))
    part['mail'].append("No. of sell orders: {:>15}".format(len(oos.sell_orders)))
    part['csv'].append("Value of buy orders " + CONF.quote + ":; {}".format(int(oos.total_buy_order_value)))
    part['csv'].append("Value of sell orders " + CONF.quote + ":; {}".format(int(oos.total_sell_order_value)))
    part['csv'].append("No. of buy orders:; {}".format(len(oos.buy_orders)))
    part['csv'].append("No. of sell orders:; {}".format(len(oos.sell_orders)))


def append_interest_rate(part: dict):
    interest_rate = get_interest_rate()
    if interest_rate is not None:
        part['mail'].append("Interest rate: {:>+20.2f}%".format(interest_rate))
        part['csv'].append("Interest rate:; {:+2f}%".format(interest_rate))
    else:
        part['mail'].append("Interest rate: {:>20}".format('n/a'))
        part['csv'].append("Interest rate:; {:}".format('n/a'))


def append_balances(part: dict, margin_balance: dict, poi: dict, wallet_balance: float, all_sold_balance: float):
    """
    Appends liquidation price, wallet balance, margin balance (including stats), used margin and leverage information
    """
    part['mail'].append("Wallet balance " + CONF.base + ": {:>18.4f}".format(wallet_balance))
    part['csv'].append("Wallet balance " + CONF.base + ":; {:.4f}".format(wallet_balance))
    price = get_current_price()
    today = calculate_daily_statistics(margin_balance['total'], price)
    append_margin_change(part, today, CONF.base)
    if all_sold_balance is not None:
        part['mail'].append("All sold balance " + CONF.base + ": {:>16.4f}".format(all_sold_balance))
        part['csv'].append("All sold balance " + CONF.base + ":; {:.4f}".format(all_sold_balance))
    else:
        part['mail'].append("All sold balance: {:>17}".format('n/a'))
        part['csv'].append("All sold balance:; {}".format('n/a'))
    append_price_change(part, today, price)
    if poi is not None and 'liquidationPrice' in poi:
        part['mail'].append("Liquidation price: {:>16.1f}".format(poi['liquidationPrice']))
        part['csv'].append("Liquidation price:; {:.1f}".format(poi['liquidationPrice']))
    else:
        part['mail'].append("Liquidation price: {:>16}".format('n/a'))
        part['csv'].append("Liquidation price:; {}".format('n/a'))
    used_margin = calculate_used_margin_percentage(margin_balance)
    part['mail'].append("Used margin: {:>22.2f}%".format(used_margin))
    part['csv'].append("Used margin:; {:.2f}%".format(used_margin))
    if CONF.exchange == 'kraken':
        actual_leverage = get_margin_leverage()
        part['mail'].append("Actual leverage: {:>18.2f}%".format(actual_leverage))
        part['csv'].append("Actual leverage:; {:.2f}%".format(actual_leverage))
    elif CONF.exchange == 'liquid':
        part['mail'].append("Actual leverage: {:>18}".format('n/a'))
        part['csv'].append("Actual leverage:; {}".format('n/a'))
    else:
        actual_leverage = get_margin_leverage()
        part['mail'].append("Actual leverage: {:>18.2f}x".format(actual_leverage))
        part['csv'].append("Actual leverage:; {:.2f}".format(actual_leverage))
    used_balance = get_position_balance()
    part['mail'].append("Position " + CONF.quote + ": {:>21}".format(used_balance))
    part['csv'].append("Position " + CONF.quote + ":; {}".format(used_balance))


def append_performance(part: dict, margin_balance: float, net_deposits: float):
    """
    Calculates and appends the absolute and relative overall performance
    """
    if net_deposits is None:
        part['mail'].append("Net deposits " + CONF.base + ": {:>17}".format('n/a'))
        part['mail'].append("Overall performance in " + CONF.base + ": {:>7}".format('n/a'))
        part['csv'].append("Net deposits " + CONF.base + ":; {}".format('n/a'))
        part['csv'].append("Overall performance in " + CONF.base + ":; {}".format('n/a'))
    else:
        part['mail'].append("Net deposits " + CONF.base + ": {:>20.4f}".format(net_deposits))
        part['csv'].append("Net deposits " + CONF.base + ":; {:.4f}".format(net_deposits))
        absolute_performance = margin_balance - net_deposits
        if net_deposits > 0:
            relative_performance = round(100 / (net_deposits / absolute_performance), 2)
            part['mail'].append(
                "Overall performance in " + CONF.base + ": {:>+10.4f} ({:+.2f}%)".format(absolute_performance,
                                                                                         relative_performance))
            part['csv'].append("Overall performance in " + CONF.base + ":; {:.4f}".format(absolute_performance))
        else:
            part['mail'].append(
                "Overall performance in " + CONF.base + ": {:>+10.4f} (% n/a)".format(absolute_performance))
            part['csv'].append("Overall performance in " + CONF.base + ":; {:.4f}".format(absolute_performance))


def append_margin_change(part: dict, today: dict, currency: str):
    """
    Appends margin changes
    """
    formatter = 18.4 if currency == CONF.base else 16.2
    m_bal = "Margin balance " + currency + ": {:>{}f}".format(today['mBal'], formatter)
    if 'mBalChan24' in today:
        m_bal += " (" if currency == CONF.base else "   ("
        m_bal += "{:+.2f}%".format(today['mBalChan24'])
        if 'mBalChan48' in today:
            m_bal += ", {:+.2f}%".format(today['mBalChan48'])
        m_bal += ")*"
    part['mail'].append(m_bal)
    formatter = .4 if currency == CONF.base else .2
    part['csv'].append("Margin balance " + currency + ":; {:{}f}".format(today['mBal'], formatter))


def append_price_change(part: dict, today: dict, price: float):
    """
    Appends price changes
    """
    rate = CONF.base + " price " + CONF.quote + ": {:>20.1f}".format(price)
    if 'priceChan24' in today:
        rate += "    ("
        rate += "{:+.2f}%".format(today['priceChan24'])
        if 'priceChan48' in today:
            rate += ", {:+.2f}%".format(today['priceChan48'])
        rate += ")*"
    part['mail'].append(rate)
    part['csv'].append(CONF.base + " price " + CONF.quote + ":; {:.1f}".format(price))


def calculate_all_sold_balance(poi: dict, sell_orders: [Order], wallet_balance: float, margin_balance: float,
                               net_deposits: float):
    if CONF.exchange == 'bitmex':
        sells = calculate_avg_entry_price_and_total_quantity(sell_orders)
        avg_sell_price = float(sells['avg'])
        tot_sell_quantity = float(sells['qty'])
        return ((float(poi['homeNotional']) - wallet_balance + margin_balance) * avg_sell_price - tot_sell_quantity) / avg_sell_price + net_deposits
    return None


def write_csv(csv: str, filename_csv: str):
    if not is_already_written(filename_csv):
        write_mode = 'a' if int(datetime.date.today().strftime("%j")) != 1 else 'w'
        with open(filename_csv, write_mode) as file:
            file.write(csv)


def is_already_written(filename_csv: str):
    if os.path.isfile(filename_csv):
        with open(filename_csv, 'r') as file:
            last_line = list(file)[-1]
            return str(datetime.date.today().isoformat()) in last_line
    return False


def send_mail(subject: str, text: str, attachment: str = None):
    recipients = ", ".join(CONF.recipient_addresses)
    msg = MIMEMultipart()
    msg['Subject'] = subject
    msg['From'] = CONF.sender_address
    msg['To'] = recipients

    readable_part = MIMEMultipart('alternative')
    readable_part.attach(MIMEText(text, 'plain', 'utf-8'))
    html = '<html><body><pre style="font:monospace">' + text + '</pre></body></html>'
    readable_part.attach(MIMEText(html, 'html', 'utf-8'))
    msg.attach(readable_part)

    if attachment and os.path.isfile(attachment):
        part = MIMEBase('application', 'octet-stream')
        with open(attachment, "rb") as file:
            part.set_payload(file.read())
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', "attachment; filename={}".format(attachment))
        msg.attach(part)

    server = smtplib.SMTP(CONF.mail_server, 587)
    server.starttls()
    server.set_debuglevel(0)
    server.login(CONF.sender_address, CONF.sender_password)
    server.send_message(msg)
    server.quit()
    LOG.info("Sent email to %s", recipients)


def calculate_daily_statistics(m_bal: float, price: float):
    """
    Calculates, updates and persists the change in the margin balance compared with yesterday
    :param m_bal: todays margin balance
    :param price: the current rate
    :return: todays statistics including price and margin balance changes compared with 24 and 48 hours ago
    """
    global STATS

    today = {'mBal': m_bal, 'price': price}
    if STATS is None:
        STATS = Stats(int(datetime.date.today().strftime("%Y%j")), today)
        persist_statistics()
        return today

    STATS.add_day(int(datetime.date.today().strftime("%Y%j")), today)
    persist_statistics()
    before_24h = STATS.get_day(int(datetime.date.today().strftime("%Y%j")) - 1)
    if before_24h is not None:
        today['mBalChan24'] = round((today['mBal']/before_24h['mBal']-1) * 100, 2)
        if 'price' in before_24h:
            today['priceChan24'] = round((today['price']/before_24h['price']-1) * 100, 2)
        before_48h = STATS.get_day(int(datetime.date.today().strftime("%Y%j")) - 2)
        if before_48h is not None:
            today['mBalChan48'] = round((today['mBal']/before_48h['mBal']-1) * 100, 2)
            if 'price' in before_48h:
                today['priceChan48'] = round((today['price']/before_48h['price']-1) * 100, 2)
    return today


def load_statistics():
    content = None
    stats_file = CONF.bot_instance + '.pkl'
    if os.path.isfile(stats_file):
        with open(stats_file, "rb") as f:
            content = pickle.load(f)
    return content


def persist_statistics():
    stats_file = CONF.bot_instance + '.pkl'
    with open(stats_file, "wb") as f:
        pickle.dump(STATS, f)


def read_moving_average():
    ma_file = 'maverage'
    if os.path.isfile(ma_file):
        with open(ma_file, "rt") as f:
            content = f.read()
        return content
    return None


def fetch_mayer(tries: int = 0):
    try:
        r = requests.get('https://mayermultiple.info/current.json')
        mayer = r.json()['data']
        return {'current': float(mayer['current_mayer_multiple']), 'average': float(mayer['average_mayer_multiple'])}

    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, requests.exceptions.ReadTimeout) as error:
        LOG.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sleep_for(4, 6)
        if tries < 4:
            return fetch_mayer(tries+1)
        LOG.warning('Failed to fetch Mayer multiple, giving up after 4 attempts')
        return None


def print_mayer():
    mayer = fetch_mayer()
    if mayer is not None:
        if mayer['current'] < mayer['average']:
            return "Mayer multiple: {:>19.2f} (< {:.2f} = BUY)".format(mayer['current'], mayer['average'])
        if mayer['current'] > 2.4:
            return "Mayer multiple: {:>19.2f} (> 2.4 = SELL)".format(mayer['current'])
        return "Mayer multiple: {:>19.2f} (> {:.2f} and < 2.4 = HOLD)".format(mayer['current'], mayer['average'])
    return


def append_mayer(part: dict):
    text = print_mayer()
    if text is not None:
        part['mail'].append(text)
        part['csv'].append(text.replace('  ', '').replace(':', ':;'))


def boost_leverage():
    if CONF.auto_leverage_escape:
        if CONF.exchange != 'bitmex':
            LOG.error("boost_leverage() not yet implemented for %s", CONF.exchange)
            return
        leverage = get_leverage()+0.1
        if leverage <= CONF.leverage_escape:
            LOG.info('Boosting leverage to {:.1f} (max: {:.1f})'.format(leverage, CONF.leverage_escape))
            set_leverage(leverage)


def set_initial_leverage():
    """
    Sets the leverage to the default level if the effective leverage is below the configured lowest level.
    Allows initialisation of cross positions
    """
    leverage = get_relevant_leverage()
    if leverage is not None and leverage < CONF.leverage_low:
        set_leverage(CONF.leverage_default)
    return True


def adjust_leverage(mayer: dict = None):
    if CONF.auto_leverage:
        if CONF.exchange != 'bitmex':
            LOG.error("Adjust_leverage() not yet implemented for %s", CONF.exchange)
            return
        if mayer is None:
            mayer = fetch_mayer()
        leverage = get_leverage()
        target_leverage = get_target_leverage(mayer)
        if leverage < target_leverage:
            LOG.debug('Leverage is lower than target leverage {:.1f} < {:.1f}'.format(leverage, target_leverage))
            set_leverage(leverage+0.1)
        elif leverage > target_leverage:
            LOG.debug('Leverage is higher than target leverage {:.1f} > {:.1f}'.format(leverage, target_leverage))
            if leverage - target_leverage > 1 and set_leverage(leverage-math.floor(leverage-target_leverage)):
                leverage = get_leverage()
            if round(leverage - target_leverage, 1) >= 0.3 and set_leverage(leverage-0.3):
                leverage = get_leverage()
            if round(leverage - target_leverage, 1) >= 0.2 and set_leverage(leverage-0.2):
                leverage = get_leverage()
            if round(leverage - target_leverage, 1) >= 0.1:
                set_leverage(leverage-0.1)


def get_target_leverage(mayer: dict):
    if mayer is not None and mayer['current'] > CONF.mm_ceil:
        return CONF.leverage_low
    if mayer is not None and mayer['current'] < CONF.mm_floor:
        return CONF.leverage_high
    return CONF.leverage_default


def get_leverage():
    try:
        if CONF.exchange == 'bitmex':
            return float(EXCHANGE.private_get_position({'symbol': CONF.symbol})[0]['leverage'])
        if CONF.exchange == 'liquid':
            response = EXCHANGE.private_get_trading_accounts()
            for pos in response:
                if pos['currency_pair_code'] == CONF.symbol:
                    return pos['leverage_level']
        LOG.error("get_leverage() not yet implemented for %s", CONF.exchange)

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        LOG.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return get_leverage()


def set_leverage(new_leverage: float):
    try:
        if CONF.exchange != 'liquid':
            EXCHANGE.private_post_position_leverage({'symbol': CONF.symbol, 'leverage': new_leverage})
            LOG.info('New leverage is {:.1f}'.format(new_leverage))
        return True

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        if any(e in str(error.args) for e in STOP_ERRORS):
            LOG.warning('Insufficient available balance - not lowering leverage to {:.1f}'.format(new_leverage))
            return False
        LOG.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return set_leverage(new_leverage)


# ------------------------------------------------------------------------------
if __name__ == '__main__':
    print('Starting Hold n Trade Bot')
    print('ccxt version:', ccxt.__version__)

    if len(sys.argv) > 1:
        INSTANCE = os.path.basename(sys.argv[1])
        if len(sys.argv) > 2:
            if sys.argv[2] == '-ac':
                AUTO_CONF = True
            elif sys.argv[2] == '-eo':
                EMAIL_ONLY = True
    else:
        INSTANCE = os.path.basename(input('Filename with API Keys (config): ') or 'config')
    LOG_FILENAME = 'log' + os.path.sep + INSTANCE

    if not EMAIL_ONLY:
        write_control_file()

    if not os.path.exists('log'):
        os.makedirs('log')

    LOG = function_logger(logging.DEBUG, LOG_FILENAME, logging.INFO)
    LOG.info('-------------------------------')
    CONF = ExchangeConfig()
    LOG.info('Holdntrade version: %s', CONF.bot_version)
    EXCHANGE = connect_to_exchange()
    STATS = load_statistics()

    if EMAIL_ONLY:
        daily_report(True)
        exit(0)

    LOOP = init_orders(False, AUTO_CONF)

    while True:
        if not HIBERNATE:
            if LOOP:
                daily_report()
                buy_executed()
                sell_executed()
                if not SELL_ORDERS:
                    LOG.info('No sell orders, resetting all orders')
                    LOOP = init_orders(True, False)
                else:
                    spread(get_current_price())
            if not LOOP:
                compensate()
                if not BUY_ORDERS and not SELL_ORDERS:
                    if not INITIAL_LEVERAGE_SET:
                        INITIAL_LEVERAGE_SET = set_initial_leverage()
                    create_first_sell_order()
                    create_first_buy_order()
                LOG.info('Initialization complete')
                LOOP = True
        else:
            daily_report()
            LOG.info('Going to hibernate')
            sleep_for(600, 900)
            adjust_leverage()
            HIBERNATE = shall_hibernate()
