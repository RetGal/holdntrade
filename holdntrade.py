#!/usr/bin/python
import configparser
import datetime
import inspect
import json
import logging
import math
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
RESET_COUNTER = 0
LOOP = False
AUTO_CONF = False
EMAIL_ONLY = False
EMAIL_SENT = 0
POSITION_INFO = False
STARTED = datetime.datetime.utcnow().replace(microsecond=0)
STATS = None
HIBERNATE = False
INITIAL_LEVERAGE_SET = False
STOP_ERRORS = ['insufficient', 'too low', 'not_enough_free_balance', 'margin_below', 'liquidation price']
RETRY_MESSAGE = 'Got an error %s %s, retrying in about 5 seconds...'

# ------------------------------------------------------------------------------


class ExchangeConfig:
    """
    Holds the configuration read from separate .txt file.
    """
    def __init__(self):

        config = configparser.ConfigParser()
        config.read(INSTANCE + ".txt")

        try:
            props = config['config']
            self.bot_instance = INSTANCE
            self.bot_version = "1.14.24"
            self.exchange = str(props['exchange']).strip('"').lower()
            self.api_key = str(props['api_key']).strip('"')
            self.api_secret = str(props['api_secret']).strip('"')
            self.test = bool(str(props['test']).strip('"').lower() == 'true')
            self.pair = str(props['pair']).strip('"')
            self.symbol = str(props['symbol']).strip('"')
            self.order_crypto_min = float(props['order_crypto_min'])
            self.satoshi_factor = 0.00000001
            self.change = abs(float(props['change']))
            self.auto_quota = bool(str(props['auto_quota']).strip('"').lower() == 'true')
            self.quota = abs(int(props['quota']))
            if self.quota < 1:
                self.quota = 1
            self.spread_factor = abs(float(props['spread_factor']))
            self.auto_leverage = bool(str(props['auto_leverage']).strip('"').lower() == 'true')
            self.auto_leverage_escape = bool(str(props['auto_leverage_escape']).strip('"').lower() == 'true')
            self.leverage_default = abs(float(props['leverage_default']))
            self.leverage_low = abs(float(props['leverage_low']))
            self.leverage_high = abs(float(props['leverage_high']))
            self.leverage_escape = abs(float(props['leverage_escape']))
            self.mm_floor = abs(float(props['mm_floor']))
            self.mm_ceil = abs(float(props['mm_ceil']))
            self.mm_stop_buy = abs(float(props['mm_stop_buy']))
            self.trade_trials = abs(int(props['trade_trials']))
            self.stop_on_top = bool(str(props['stop_on_top']).strip('"').lower() == 'true')
            self.close_on_stop = bool(str(props['close_on_stop']).strip('"').lower() == 'true')
            currency = self.pair.split("/")
            self.base = currency[0]
            self.quote = currency[1]
            self.send_emails = bool(str(props['send_emails']).strip('"').lower() == 'true')
            self.recipient_addresses = str(props['recipient_addresses']).strip('"').replace(' ', '').split(",")
            self.sender_address = str(props['sender_address']).strip('"')
            self.sender_password = str(props['sender_password']).strip('"')
            self.mail_server = str(props['mail_server']).strip('"')
        except (configparser.NoSectionError, KeyError):
            raise SystemExit('invalid configuration for ' + INSTANCE)


class OpenOrdersSummary:
    """
    Creates and holds an open orders summary
    """
    __slots__ = 'sell_orders', 'buy_orders', 'total_sell_order_value', 'total_buy_order_value'

    def __init__(self, open_orders):
        self.sell_orders = ()
        self.buy_orders = ()
        self.total_sell_order_value = 0
        self.total_buy_order_value = 0

        sells = []
        buys = []
        for oo in open_orders:
            o = Order(oo)
            if o.side == 'sell':
                if CONF.exchange == 'bitmex':
                    self.total_sell_order_value += o.amount
                else:
                    self.total_sell_order_value += o.amount * o.price
                sells.append(o)
            elif o.side == 'buy':
                if CONF.exchange == 'bitmex':
                    self.total_buy_order_value += o.amount
                else:
                    self.total_buy_order_value += o.amount * o.price
                buys.append(o)
            else:
                LOG.error(inspect.stack()[1][3], ' ?!?')

        self.sell_orders = tuple(sorted(sells, key=lambda order: order.price, reverse=True))  # desc
        self.buy_orders = tuple(sorted(buys, key=lambda order: order.price, reverse=True))  # desc

    def get_orders(self):
        return tuple(self.sell_orders + self.buy_orders)


class Order:
    """
    Creates and holds the relevant data of an order
    """
    __slots__ = 'id', 'price', 'amount', 'side', 'datetime'

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
        if self.get_day(day_of_year) is None:
            data['day'] = day_of_year
            if len(self.days) > 2:
                self.days = sorted(self.days, key=lambda item: item['day'], reverse=True)  # desc
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
    global BUY_ORDERS
    global HIBERNATE
    global INITIAL_LEVERAGE_SET
    global SELL_PRICE

    LOG.debug('----------------------------------')
    LOG.debug(time.ctime())

    if CURR_BUY_ORDER is None:
        if not CONF.stop_on_top:
            LOG.warning('Current buy order is None')
        return

    status = fetch_order_status(CURR_BUY_ORDER.id)
    if status == 'open':
        price = get_current_price()
        LOG.debug('Open Buy Order! Amount: %s @ %.1f', str(CURR_BUY_ORDER.amount), float(BUY_PRICE))
        LOG.debug('Current Price: %s', price)
    elif status in ['closed', 'canceled']:
        LOG.info('Buy executed %s, starting follow up', str(CURR_BUY_ORDER))
        # use amount of last (previous) buy order for next sell order
        last_buy_amount = CURR_BUY_ORDER.amount
        if CURR_BUY_ORDER in BUY_ORDERS:
            BUY_ORDERS.remove(CURR_BUY_ORDER)
        if not INITIAL_LEVERAGE_SET:
            INITIAL_LEVERAGE_SET = set_initial_leverage()
        mamu = fetch_mayer()
        adjust_leverage(mamu)
        HIBERNATE = shall_hibernate(mamu)
        if not HIBERNATE:
            price = get_current_price()
            if keep_buying(price):
                create_buy_order(price, calculate_buy_order_amount(), False)
            else:
                SELL_PRICE = round(price * (1 + CONF.change))
            create_sell_order(last_buy_amount)
    else:
        LOG.warning('Should not be here, order status is %s', status)


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
            LOG.info('Sell executed %s', str(order))
            if CONF.stop_on_top and CONF.close_on_stop and not SELL_ORDERS:
                return
            mamu = fetch_mayer()
            adjust_leverage(mamu)
            HIBERNATE = shall_hibernate(mamu)
            if not HIBERNATE:
                if not SELL_ORDERS:
                    create_sell_order(calculate_sell_order_amount())
                cancel_current_buy_order()
                price = get_current_price()
                if keep_buying(price):
                    create_buy_order(price, calculate_buy_order_amount(), False)
        else:
            LOG.warning('Should not be here, order status: %s', status)


def keep_buying(price: float):
    """
    Checks if it makes sense to create another buy order although the bot is configured to sell out
    :param price: current market price
    :return: True or False
    """
    if not CONF.stop_on_top:
        return True
    if SELL_ORDERS:
        return round(price * (1 + CONF.change)) < sorted(SELL_ORDERS, key=lambda order: order.price, reverse=True)[0].price
    return False


def shall_hibernate(mayer: dict = None):
    if mayer is None:
        mayer = fetch_mayer()
    if mayer is not None and mayer['current']:
        if mayer['current'] > CONF.mm_stop_buy:
            return True
        if not CONF.auto_leverage:
            return round(get_leverage(), 1) > CONF.leverage_default
        if CONF.auto_leverage_escape:
            return round(get_leverage(), 1) > CONF.leverage_escape
        return round(get_leverage(), 1) > get_target_leverage(mayer)
    return HIBERNATE


def cancel_current_buy_order():
    """
    Cancels the current buy order
    """
    global CURR_BUY_ORDER
    global BUY_ORDERS

    if CURR_BUY_ORDER is not None:
        cancel_order(CURR_BUY_ORDER)
        if CURR_BUY_ORDER in BUY_ORDERS:
            BUY_ORDERS.remove(CURR_BUY_ORDER)
        LOG.info('Canceled current %s', str(CURR_BUY_ORDER))
        CURR_BUY_ORDER = None if not BUY_ORDERS else BUY_ORDERS[0]


def create_first_sell_order():
    global SELL_PRICE

    SELL_PRICE = round(get_current_price() * (1 + CONF.change))
    create_sell_order(calculate_sell_order_amount())


def calculate_sell_order_amount():
    """
    Calculates the sell order amount.
    :return amount to be sold in fiat
    """
    available = get_position_balance()
    quota = calculate_quota() if CONF.auto_quota else CONF.quota
    LOG.info("Calculating sell order amount (%s / %s)", available, quota)
    return math.floor(available / quota)


def create_first_buy_order():
    global HIBERNATE

    mamu = fetch_mayer()
    adjust_leverage(mamu)
    HIBERNATE = shall_hibernate(mamu)
    if not HIBERNATE:
        price = get_current_price()
        create_buy_order(price, calculate_buy_order_amount(price), False)


def create_sell_order(fixed_order_size: int = None):
    """
    :param fixed_order_size the order volume (optional)
    Creates a sell order. Relies on the global set SELL_PRICE. Used by other functions.
    It appends the created order to the global SELL_ORDERS list.
    """
    global SELL_PRICE
    global SELL_ORDERS

    order_size = fixed_order_size if fixed_order_size is not None else CURR_BUY_ORDER.amount if CURR_BUY_ORDER is not None else 0

    available = get_position_balance()
    if available < order_size:
        # sold out - the main loop will re-init if there are no other sell orders open
        LOG.warning('Not executing sell order over %d (only %d left)', order_size, available)
        return False
    if is_order_below_limit(order_size, SELL_PRICE):
        return False

    try:
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
        return True

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        if any(e in str(error.args) for e in STOP_ERRORS):
            LOG.error('Insufficient funds - not selling %d', order_size)
            return False
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        SELL_PRICE = round(get_current_price() * (1 + CONF.change))
        create_sell_order(fixed_order_size)


def fetch_order_status(order_id: str):
    """
    Fetches the status of an order
    :param order_id of an order
    :return status of the order (open, closed)
    """
    try:
        return EXCHANGE.fetch_order_status(order_id)

    except ccxt.OrderNotFound as error:
        LOG.error('Order status not found  %s %s', order_id, str(error.args))
        return 'not found'
    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        fetch_order_status(order_id)


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
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        cancel_order(order)


def create_buy_order(price: float, buy_amount: int, fixed_price: bool = False):
    """
    Creates a buy order for the requested amount. The order price is calculated using the configured change.
    :param price current price of crypto
    :param buy_amount the order volume
    :param fixed_price buys to the requested price without subtracting change
    output: calculate the SELL_PRICE (price + change) and the BUY_PRICE (price - change).
    In addition sets the CURR_ORDER and adds the created order to the BUY_ORDERS as global values.
    If the amount is below the order limit or there is not enough margin and there are open sell orders, the function
    is going to sleep, allowing sell orders to be filled - afterwards the amount is recalculated and the function calls
    itself with the new amount
    """
    global SELL_PRICE
    global BUY_PRICE
    global CURR_BUY_ORDER
    global BUY_ORDERS

    BUY_PRICE = price if fixed_price else round(price * (1 - CONF.change))
    SELL_PRICE = round(price * (1 + CONF.change))
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
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        create_buy_order(update_price(curr_price, price), buy_amount, fixed_price)


def delay_buy_order(crypto_price: float, price: float):
    """
    Delays the creation of a buy order, allowing sell orders to be filled - afterwards the amount is recalculated and
    the function calls create_buy_order with the current price and the new amount
    :param crypto_price: the crypto rate with which price was calculated
    :param price: the price of the original buy order to be created
    """
    sleep_for(90, 180)
    daily_report()
    new_amount = calculate_buy_order_amount()  # recalculate order size
    if is_order_below_limit(new_amount, update_price(crypto_price, price)):
        if CONF.auto_leverage and CONF.auto_leverage_escape:
            boost_leverage()
        elif CONF.auto_leverage:
            adjust_leverage()
    create_buy_order(update_price(crypto_price, price), calculate_buy_order_amount(), False)


def calculate_buy_order_amount(price: float = None):
    """
    Calculates the buy order amount.
    :return amount to be bought in fiat
    """
    wallet_available = get_balance()['free']
    if CONF.exchange == 'liquid':
        orders = EXCHANGE.private_get_orders({'status': 'live', 'side': 'sell'})['models']
        used = 0
        if orders:
            for order in orders:
                used += float(order['quantity'])
            wallet_available -= used
    if wallet_available < 0:
        return 0
    if price is None:
        price = get_current_price()
    quota = calculate_quota(price) if CONF.auto_quota else CONF.quota
    LOG.info("Calculating buy order amount (%s / %s * %s)", wallet_available, quota, price)
    return math.floor(wallet_available / quota * price) if price is not None else 0


def create_market_sell_order(amount_crypto: float):
    """
    Creates a market sell order and sets the values as global ones. Used to compensate margins above 50%.
    :param amount_crypto to be sold (to reach 50% margin)
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
                new_order = EXCHANGE.create_market_sell_order(CONF.pair, amount_crypto,
                                                              {'leverage': CONF.leverage_default})
            elif CONF.exchange == 'liquid':
                new_order = EXCHANGE.create_market_sell_order(CONF.pair, amount_fiat,
                                                              {'leverage_level': CONF.leverage_default})
            order = Order(new_order)
            LOG.info('Created market %s', str(order))

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        if any(e in str(error.args) for e in STOP_ERRORS):
            LOG.error('Insufficient balance/funds - not selling %d', amount_fiat)
            return
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        create_market_sell_order(amount_crypto)


def create_market_buy_order(amount_crypto: float):
    """
    Creates a market buy order and sets the values as global ones. Used to compensate margins below 50%.
    :param amount_crypto to be bought (to reach 50% margin)
    """
    global BUY_PRICE
    global SELL_PRICE

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

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        if "not_enough_free" or "free_margin_below" in str(error.args):
            LOG.error('Not enough free margin/balance %s %s', type(error).__name__, str(error.args))
            return

        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        create_market_buy_order(amount_crypto)


def get_margin_leverage():
    """
    Fetch the leverage
    :return margin leverage: float
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
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        get_margin_leverage()


def get_relevant_leverage():
    """
    Returns the higher of the two leverages - used to set the initial leverage
    :return leverage: float
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
    :return balance in crypto: float
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
                for balance in result:
                    if balance['currency'] == CONF.base:
                        return float(balance['balance'])
        return None

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        get_wallet_balance()


def get_balance():
    """
    Fetch the balance in crypto.
    :return balance in crypto dict: used: float, free: float,total: float
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
        pos = get_position_info()
        if pos is not None:
            bal = {'used': float(pos['margin']), 'free': float(pos['free_margin']), 'total': float(pos['equity'])}
        if bal is None:
            # no position => return wallet balance
            result = EXCHANGE.private_get_accounts_balance()
            if result is not None:
                for wallet in result:
                    if wallet['currency'] == CONF.base:
                        bal = {'used': 0, 'free': float(wallet['balance']), 'total': float(wallet['balance'])}
        return bal

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        get_balance()


def get_position_balance():
    """
    Fetch the position balance in fiat.
    :return balance: int
    """
    try:
        if CONF.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase']:
            return EXCHANGE.private_get_position()[0]['currentQty']
        if CONF.exchange == 'kraken':
            result = EXCHANGE.private_post_tradebalance()['result']
            return round(float(result['e']) - float(result['mf']))
        if CONF.exchange == 'liquid':
            return round(get_balance()['used'] * get_current_price())
        return None

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        get_position_balance()


def get_net_deposits():
    """
    Get deposits and withdraws to calculate the net deposits in crypto.
    :return net deposits: float
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
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        get_net_deposits()


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
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        get_position_info()


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
        LOG.error("get_interest_rate() not yet implemented for %s", CONF.exchange)
        return None

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        get_interest_rate()


def compensate():
    """
    Approaches the margin used towards 50% by selling or buying the difference to market price
    """
    if CONF.stop_on_top:
        return
    if CONF.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase', 'liquid']:
        bal = get_balance()
    elif CONF.exchange == 'kraken':
        bal = get_margin_balance()

    used = float(100 - (bal['free'] / bal['total']) * 100)
    if used < 40 or used > 60:
        amount_crypto = float(bal['total'] / 2 - bal['used'])
        if amount_crypto > 0:
            LOG.info("Need to buy %s %s in order to reach %s margin", amount_crypto, CONF.base, '50%')
            do_buy(amount_crypto)
        else:
            LOG.info("Need to sell %s %s in order to reach %s margin", abs(amount_crypto), CONF.base, '50%')
            do_sell(abs(amount_crypto))


def do_buy(crypto_amount: float):
    """
    Market price raised in 0.5 steps
    """
    global CURR_BUY_ORDER
    global BUY_ORDERS

    i = 1
    while i <= CONF.trade_trials:
        rise = i / 2
        buy_price = get_current_price() + rise
        if not create_buy_order(buy_price, round(crypto_amount * buy_price), True):
            return
        sleep_for(89, 91)
        order_status = fetch_order_status(CURR_BUY_ORDER.id)
        if order_status in ['open', 'not found']:
            cancel_current_buy_order()
            i += 1
            daily_report()
        else:
            if CURR_BUY_ORDER in BUY_ORDERS:
                BUY_ORDERS.remove(CURR_BUY_ORDER)
            CURR_BUY_ORDER = None if not BUY_ORDERS else BUY_ORDERS[0]
            return
    create_market_buy_order(crypto_amount)


def do_sell(crypto_amount: float):
    """
    Market price discounted in 0.5 steps
    """
    global SELL_PRICE
    global SELL_ORDERS

    i = 1
    while i <= CONF.trade_trials:
        discount = i / 2
        SELL_PRICE = get_current_price() - discount
        if not create_sell_order(round(crypto_amount * SELL_PRICE)):
            return
        sleep_for(89, 91)
        order_status = fetch_order_status(SELL_ORDERS[-1].id)
        if order_status in ['open', 'not found']:
            cancel_order(SELL_ORDERS[-1])
            del SELL_ORDERS[-1]
            i += 1
            daily_report()
        else:
            del SELL_ORDERS[-1]
            return
    create_market_sell_order(crypto_amount)


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
                if create_buy_order(price, highest_buy_order.amount, False):
                    create_sell_order()


def get_margin_balance():
    """
    Fetches the margin balance in fiat (free and total)
    :return balance in fiat
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
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        get_margin_balance()


def calculate_used_margin_percentage(bal=None):
    """
    Calculates the used margin percentage
    """
    if bal is None:
        bal = get_margin_balance()
        if bal['total'] <= 0:
            return 0
    return float(100 - (bal['free'] / bal['total']) * 100)


def calculate_order_stats(open_orders: [Order]):
    """"
    Calculates the average price and the fiat/crypto quantity (value) of a list of open orders
    :param open_orders: [Order]
    """
    total_amount_fiat = 0
    total_amount_crypto = 0
    total_price = 0
    for order in open_orders:
        total_amount_fiat += order.amount
        total_amount_crypto += order.amount / order.price
        total_price += order.price * order.amount
    if total_amount_fiat > 0:
        return {'avg':  total_price / total_amount_fiat, 'qty': total_amount_fiat, 'val': total_amount_crypto}
    return {'avg': 0, 'qty': 0}


def get_current_price():
    """
    Fetch the current crypto price
    :return last bid price: float
    """
    try:
        price = EXCHANGE.fetch_ticker(CONF.pair)['bid']
        if not price:
            LOG.warning('Price was None')
            sleep_for(1, 2)
            get_current_price()
        else:
            return price

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        if "key is disabled" in str(error.args):
            LOG.warning('Key is disabled')
            return deactivate_bot()
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        get_current_price()


def update_price(origin_price: float, price: float):
    """
    Update the price by considering the old and current price
    :param origin_price
    :param price
    :return price float:
    """
    return (get_current_price() / origin_price) * price


def init_orders(force_close: bool, auto_conf: bool):
    """
    Initialize existing orders or remove all pending ones
    output True if loaded and False if compensate margin is necessary
    :param force_close: close all orders/positions (reset)
    :param auto_conf: load all orders and keep position
    :return False if compensate is required, True if not
    """
    global SELL_PRICE
    global SELL_ORDERS
    global CURR_BUY_ORDER
    global BUY_ORDERS
    global BUY_PRICE
    global RESET_COUNTER

    if force_close:
        RESET_COUNTER += 1

    try:
        if auto_conf:
            LOG.warning("Bot was resurrected by hades")

        # Handle open orders
        oos = get_open_orders()

        LOG.info("Used margin: {:>20.2f}%".format(calculate_used_margin_percentage()))
        print_position_info(oos)

        if oos.get_orders():
            LOG .info("Value of buy orders {}: {:>5}".format(CONF.quote, int(oos.total_buy_order_value)))
            LOG.info("Value of sell orders {}: {:>4}".format(CONF.quote, int(oos.total_sell_order_value)))
            LOG.info("No. of buy orders: {:>11}".format(len(oos.buy_orders)))
            LOG.info("No. of sell orders: {:>10}".format(len(oos.sell_orders)))
            LOG.info('----------------------------------')

            cancel_existing_orders = False
            if not force_close and not auto_conf:
                keep_existing_orders = input('There are open orders! Would you like to load them? (y/n) ')
                cancel_existing_orders = keep_existing_orders.lower() not in ['y', 'yes']

            if not force_close and (auto_conf or not cancel_existing_orders):
                auto_configure(oos)
                LOG.info('Initialization complete (using existing orders)')
                # No "compensate" in auto configuration
                return True

            LOG.info('Unrealised PNL: %s %s', str(get_unrealised_pnl(CONF.symbol) * CONF.satoshi_factor), CONF.base)
            if force_close or cancel_existing_orders:
                cancel_orders(oos.get_orders())

            if not force_close:
                clear_position = input('There is an open ' + CONF.base + ' position! Would you like to close it? (y/n) ')
                if clear_position.lower() in ['y', 'yes']:
                    cancel_orders(oos.get_orders())
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
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return init_orders(force_close, auto_conf)

    del oos
    # compensate
    return False


def auto_configure(oos: OpenOrdersSummary):
    load_existing_orders(oos)
    if not CONF.stop_on_top:
        adjust_leverage()
        if not oos.sell_orders:
            create_first_sell_order()
        if not oos.buy_orders:
            create_first_buy_order()
    del oos


def load_existing_orders(oos: OpenOrdersSummary):
    global SELL_ORDERS
    global SELL_PRICE
    global BUY_ORDERS
    global CURR_BUY_ORDER
    global BUY_PRICE

    if oos.sell_orders:
        SELL_ORDERS = list(oos.sell_orders)
        SELL_PRICE = SELL_ORDERS[-1].price  # lowest if several
    if oos.buy_orders:
        BUY_ORDERS = list(oos.buy_orders)
        CURR_BUY_ORDER = BUY_ORDERS[0]  # highest if several
        BUY_PRICE = CURR_BUY_ORDER.price


def cancel_orders(orders: [Order]):
    """
    Close a list of orders
    :param orders: [Order]
    """
    try:
        for order in orders:
            LOG.debug('Cancel %s', str(order))
            status = EXCHANGE.fetch_order_status(order.id)
            if status == 'open':
                EXCHANGE.cancel_order(order.id)
            else:
                LOG.warning('Cancel %s was in state %s', str(order), status)

    except ccxt.OrderNotFound as error:
        LOG.error('Cancel %s not found : %s', str(order), str(error.args))
        return
    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        cancel_orders(orders)


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
        # no retry in case of "system is currently overloaded" (bitmex specific error)
        if "overloaded" in str(error.args):
            LOG.info('Exchange is overloaded, close position is postponed')
            return
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        close_position(symbol)


def get_open_position(symbol: str):
    """
    Get all open positions
    :return positions
    """
    try:
        if CONF.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase']:
            for position in EXCHANGE.private_get_position():
                if position['isOpen'] and position['symbol'] == symbol:
                    return position
        elif CONF.exchange == 'kraken':
            response = EXCHANGE.private_post_openpositions()
            if response['result'] == 'success':
                for position in response['openPositions']:
                    if position['symbol'] == symbol:
                        return position
        elif CONF.exchange == 'liquid':
            trades = EXCHANGE.private_get_trades({'status': 'open'})
            for model in trades['models']:
                if model['currency_pair_code'] == CONF.pair:
                    return model
        return None

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        get_open_position(symbol)


def get_open_orders(tries: int = 0):
    """
    Gets all open orders
    :return OpenOrdersSummary
    """
    try:
        return OpenOrdersSummary(EXCHANGE.fetch_open_orders(CONF.pair, since=None, limit=None, params={}))

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        if "key is disabled" in str(error.args):
            LOG.warning('Key is disabled')
            return deactivate_bot()

        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        if tries < 20000:
            get_open_orders(tries+1)
        return None


def get_unrealised_pnl(symbol: str):
    """
    Returns the unrealised pnl for the requested currency
    :param symbol:
    :return float
    """
    try:
        if get_open_position(symbol) is not None:
            return float(get_open_position(symbol)['unrealisedPnl'])
        return 0.0

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        get_unrealised_pnl(symbol)


def print_position_info(oos: OpenOrdersSummary):
    if CONF.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase']:
        sleep_for(1, 2)
        poi = get_position_info()
        if poi:
            LOG.info("Position {}: {:>16}".format(CONF.quote, poi['currentQty']))
            LOG.info("Entry price: {:>19.1f}".format(poi['avgEntryPrice']))
            LOG.info("Market price: {:>18.1f}".format(poi['markPrice']))
            LOG.info("Liquidation price: {:>13.1f}".format(poi['liquidationPrice']))
            del poi
        else:
            LOG.info("Available balance is {}: {:>6} ".format(CONF.base, get_balance()['free']))
            LOG.info("No position found, I will create one for you")
            return
    elif CONF.exchange == 'kraken':
        LOG.info("Position {}: {:>16}".format(CONF.quote, get_position_balance()))
        LOG.info("Entry price: {:>19.1f}".format(calculate_order_stats(oos.get_orders())['avg']))
        LOG.info("Market price: {:>18.1f}".format(get_current_price()))
    elif CONF.exchange == 'liquid':
        poi = get_position_info()
        if poi is not None and float(poi['position']) > 0:
            LOG.info("Position {}: {:>16.2f}".format(CONF.base, float(poi['position'])))
        else:
            LOG.info("Available balance is {}: {:>6} ".format(CONF.base, get_balance()['free']))
            LOG.info("No position found, I will create one for you")
            return
    if not oos.get_orders():
        LOG.info("No open orders")


def connect_to_exchange():
    """
    Connects to the exchange.
    :return exchange
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

    # pprint(dir(exchange))

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
    return round(fiat_amount / price - 0.000000006, 8)


def write_control_file():
    with open(INSTANCE + '.pid', 'w') as file:
        file.write(str(os.getpid()) + ' ' + INSTANCE)


def write_position_info(info: str):
    if info is not None:
        LOG.info('Writing %s', INSTANCE + '.position.info.json')
        with open(INSTANCE + '.position.info.json', 'w') as file:
            file.write(info)


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
            compact_position()
            subject = "Daily report for {}".format(CONF.bot_instance)
            content = create_mail_content()
            filename_csv = CONF.bot_instance + '.csv'
            write_csv(content['csv'], filename_csv)
            send_mail(subject, content['text'], filename_csv)
            EMAIL_SENT = now.day


def create_mail_content():
    """
    Fetches and formats the data required for the daily report email
    :return dict: text: str, csv: str
    """
    price = get_current_price()
    performance_part = create_report_part_performance(price)
    advice_part = create_report_part_advice(price)
    settings_part = create_report_part_settings(price)
    general_part = create_mail_part_general()

    performance = ["Performance", "-----------", '\n'.join(performance_part['mail']) + '\n* (change within 24 hours)', '\n\n']
    advice = ["Assessment / advice", "-------------------", '\n'.join(advice_part['mail']), '\n\n']
    settings = ["Your settings", "-------------", '\n'.join(settings_part['mail']), '\n\n']
    general = ["General", "-------", '\n'.join(general_part), '\n\n']

    bcs_url = 'https://bitcoin-schweiz.ch/bot/'
    explanation = 'Erläuterungen zu diesem Rapport: https://bitcoin-schweiz.ch/wp-content/uploads/2019/07/Tagesrapport.pdf'
    text = '\n'.join(performance) + '\n'.join(advice) + '\n'.join(settings) + '\n'.join(general) + bcs_url + '\n\n' + explanation + '\n'

    csv = CONF.bot_instance + ';' + str(datetime.datetime.utcnow().replace(microsecond=0)) + ' UTC;' + (';'.join(performance_part['csv']) + ';' + ';'.join(
        advice_part['csv']) + ';' + ';'.join(settings_part['csv']) + '\n')

    return {'text': text, 'csv': csv}


def create_report_part_settings(price: float):
    quota = calculate_quota(price) if CONF.auto_quota else CONF.quota
    return {'mail': ["Rate change: {:>22.1f}%".format(CONF.change * 100),
                     "Quota: {:>28}".format('1/' + str(quota)),
                     "Auto quota: {:>23}".format(str('Y' if CONF.auto_quota is True else 'N')),
                     "Spread factor: {:>20}".format(str(CONF.spread_factor)),
                     "Leverage default: {:>17}x".format(str(CONF.leverage_default)),
                     "Auto leverage: {:>20}".format(str('Y' if CONF.auto_leverage is True else 'N')),
                     "Auto leverage escape: {:>13}".format(str('Y' if CONF.auto_leverage_escape is True else 'N')),
                     "Leverage low: {:>21}x".format(str(CONF.leverage_low)),
                     "Leverage high: {:>20}x".format(str(CONF.leverage_high)),
                     "Leverage escape: {:>18}x".format(str(CONF.leverage_high)),
                     "Mayer multiple floor: {:>13}".format(str(CONF.mm_floor)),
                     "Mayer multiple ceil: {:>14}".format(str(CONF.mm_ceil)),
                     "Mayer multiple stop buy: {:>10}".format(str(CONF.mm_stop_buy)),
                     "Stop on top: {:>22}".format(str('Y' if CONF.stop_on_top is True else 'N' if CONF.close_on_stop is False else '(!) N')),
                     "Close on stop: {:>20}".format(str('Y' if CONF.close_on_stop is True and CONF.stop_on_top is True else '(!) Y' if CONF.close_on_stop is True and CONF.stop_on_top is False else 'N'))],
            'csv': ["Rate change:;{:.1f}%".format(float(CONF.change * 100)),
                    "Quota:;'1/{}'".format(str(quota)),
                    "Auto quota:;{}".format(str('Y' if CONF.auto_quota is True else 'N')),
                    "Spread factor:;{}".format(str(CONF.spread_factor)),
                    "Leverage default:;{}".format(str(CONF.leverage_default)),
                    "Auto leverage:;{}".format(str('Y' if CONF.auto_leverage is True else 'N')),
                    "Auto leverage escape:;{}".format(str('Y' if CONF.auto_leverage_escape is True else 'N')),
                    "Leverage low:;{}".format(str(CONF.leverage_low)),
                    "Leverage high:;{}".format(str(CONF.leverage_high)),
                    "Leverage escape:;{}".format(str(CONF.leverage_escape)),
                    "Mayer multiple floor:;{}".format(str(CONF.mm_floor)),
                    "Mayer multiple ceil:;{}".format(str(CONF.mm_ceil)),
                    "Mayer multiple stop buy:;{}".format(str(CONF.mm_stop_buy)),
                    "Stop on top:;{}".format(str('Y' if CONF.stop_on_top is True else 'N' if CONF.close_on_stop is False else '(!) N')),
                    "Close on stop:;{}".format(str('Y' if CONF.close_on_stop is True and CONF.stop_on_top is True else '(!) Y' if CONF.close_on_stop is True and CONF.stop_on_top is False else 'N'))]}


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


def create_report_part_advice(price: float):
    moving_average = read_moving_average()
    if moving_average is not None:
        padding = 6 + len(moving_average)
        part = {'mail': ["Moving average 144d/21d: {:>{}}".format(moving_average, padding)],
                'csv': ["Moving average 144d/21d:;{}".format(moving_average.replace(' = ', ';').replace(' (', ';('))]}
    else:
        part = {'mail': ["Moving average 144d/21d: {:>10}".format('n/a')],
                'csv': ["Moving average 144d/21d:;n/a;n/a;n/a"]}
    append_mayer(part)
    return part


def create_report_part_performance(price: float):
    part = {'mail': [], 'csv': []}
    margin_balance = get_margin_balance()
    net_deposits = get_net_deposits()
    sleep_for(0, 1)
    append_performance(part, margin_balance['total'], net_deposits)
    poi = get_position_info()
    wallet_balance = get_wallet_balance()
    sleep_for(0, 1)
    oos = get_open_orders()
    all_sold_balance = calculate_all_sold_balance(poi, oos.sell_orders, margin_balance['total'])
    append_balances(part, margin_balance, poi, wallet_balance, price, all_sold_balance)
    append_orders(part, oos, price)
    append_interest_rate(part)
    return part


def append_orders(part: dict, oos: OpenOrdersSummary, price: float):
    """
    Appends order statistics
    """
    part['mail'].append("Value of buy orders {}: {:>10}".format(CONF.quote, int(oos.total_buy_order_value)))
    part['mail'].append("Value of sell orders {}: {:>9}".format(CONF.quote, int(oos.total_sell_order_value)))
    part['mail'].append("No. of buy orders: {:>16}".format(len(oos.buy_orders)))
    part['mail'].append("No. of sell orders: {:>15}".format(len(oos.sell_orders)))
    append_order_offset(part, oos, price)
    part['csv'].append("Value of buy orders {}:;{}".format(CONF.quote, int(oos.total_buy_order_value)))
    part['csv'].append("Value of sell orders {}:;{}".format(CONF.quote, int(oos.total_sell_order_value)))
    part['csv'].append("No. of buy orders:;{}".format(len(oos.buy_orders)))
    part['csv'].append("No. of sell orders:;{}".format(len(oos.sell_orders)))


def append_order_offset(part: dict, oos: OpenOrdersSummary, price: float):
    highest_buy = oos.buy_orders[0].price if oos.buy_orders else None
    if highest_buy is not None:
        buy_offset = calculate_price_offset(highest_buy, price)
        part['mail'].append("Highest buy order {}: {:>12} ({}% below actual {} price)".format(CONF.quote,
                                                                                              highest_buy,
                                                                                              buy_offset,
                                                                                              CONF.base))
        part['csv'].append("Highest buy order {}:;{}".format(CONF.quote, highest_buy))
    else:
        part['mail'].append("Highest buy order {}: {:>12}".format(CONF.quote, 'n/a'))
        part['csv'].append("Highest buy order {}:;{}".format(CONF.quote, 'n/a'))

    lowest_sell = oos.sell_orders[-1].price if oos.sell_orders else None
    if lowest_sell is not None:
        sell_offset = calculate_price_offset(lowest_sell, price)
        part['mail'].append("Lowest sell order {}: {:>12} ({}% above actual {} price)".format(CONF.quote,
                                                                                              lowest_sell,
                                                                                              sell_offset,
                                                                                              CONF.base))
        part['csv'].append("Lowest sell order {}:;{}".format(CONF.quote, lowest_sell))
    else:
        part['mail'].append("Lowest sell order {}: {:>12}".format(CONF.quote, 'n/a'))
        part['csv'].append("Lowest sell order {}:;{}".format(CONF.quote, 'n/a'))


def append_interest_rate(part: dict):
    interest_rate = get_interest_rate()
    if interest_rate is not None:
        part['mail'].append("Interest rate: {:>+20.2f}%".format(interest_rate))
        part['csv'].append("Interest rate:;{:+.2f}%".format(interest_rate))
    else:
        part['mail'].append("Interest rate: {:>20}".format('n/a'))
        part['csv'].append("Interest rate:;{}".format('n/a'))


def append_balances(part: dict, margin_balance: dict, poi: dict, wallet_balance: float, price: float,
                    all_sold_balance: float = None):
    """
    Appends liquidation price, wallet balance, margin balance (including stats), used margin and leverage information
    """
    part['mail'].append("Wallet balance {}: {:>18.4f}".format(CONF.base, wallet_balance))
    part['csv'].append("Wallet balance {}:;{:.4f}".format(CONF.base, wallet_balance))
    today = calculate_daily_statistics(margin_balance['total'], price)
    append_margin_change(part, today, CONF.base)
    part['mail'].append("Available balance {}: {:>15.4f}".format(CONF.base, margin_balance['free']))
    part['csv'].append("Available balance {}:;{:.4f}".format(CONF.base, margin_balance['free']))
    if all_sold_balance is not None:
        part['mail'].append("All sold balance {}: {:>16.4f}".format(CONF.base, all_sold_balance))
        part['csv'].append("All sold balance {}:;{:.4f}".format(CONF.base, all_sold_balance))
    else:
        part['mail'].append("All sold balance: {:>17}".format('n/a'))
        part['csv'].append("All sold balance:;n/a")
    append_price_change(part, today, price)
    if poi is not None and 'liquidationPrice' in poi:
        part['mail'].append("Liquidation price {}: {:>12.1f}".format(CONF.quote, poi['liquidationPrice']))
        part['csv'].append("Liquidation price {}:;{:.1f}".format(CONF.quote, poi['liquidationPrice']))
    else:
        part['mail'].append("Liquidation price {}: {:>12}".format(CONF.quote, 'n/a'))
        part['csv'].append("Liquidation price {}:;{}".format(CONF.quote, 'n/a'))
    used_margin = calculate_used_margin_percentage(margin_balance)
    part['mail'].append("Used margin: {:>22.2f}%".format(used_margin))
    part['csv'].append("Used margin:;{:.2f}%".format(used_margin))
    if CONF.exchange == 'kraken':
        actual_leverage = get_margin_leverage()
        part['mail'].append("Actual leverage: {:>18.2f}%".format(actual_leverage))
        part['csv'].append("Actual leverage:;{:.2f}%".format(actual_leverage))
    elif CONF.exchange == 'liquid':
        part['mail'].append("Actual leverage: {:>18}".format('n/a'))
        part['csv'].append("Actual leverage:;{}".format('n/a'))
    else:
        actual_leverage = get_margin_leverage()
        part['mail'].append("Actual leverage: {:>18.2f}x".format(actual_leverage))
        part['csv'].append("Actual leverage:;{:.2f}".format(actual_leverage))
    used_balance = get_position_balance()
    part['mail'].append("Position {}: {:>21}".format(CONF.quote, used_balance))
    part['csv'].append("Position {}:;{}".format(CONF.quote, used_balance))


def append_performance(part: dict, margin_balance: float, net_deposits: float):
    """
    Calculates and appends the absolute and relative overall performance
    """
    if net_deposits is None:
        part['mail'].append("Net deposits {}: {:>17}".format(CONF.base, 'n/a'))
        part['mail'].append("Overall performance in {}: {:>7}".format(CONF.base, 'n/a'))
        part['csv'].append("Net deposits {}:;{}".format(CONF.base, 'n/a'))
        part['csv'].append("Overall performance in {}:;{}".format(CONF.base, 'n/a'))
    else:
        part['mail'].append("Net deposits {}: {:>20.4f}".format(CONF.base, net_deposits))
        part['csv'].append("Net deposits {}:;{:.4f}".format(CONF.base, net_deposits))
        absolute_performance = margin_balance - net_deposits
        if net_deposits > 0:
            relative_performance = round(100 / (net_deposits / absolute_performance), 2)
            part['mail'].append(
                "Overall performance in " + CONF.base + ": {:>+10.4f} ({:+.2f}%)".format(absolute_performance,
                                                                                         relative_performance))
            part['csv'].append("Overall performance in " + CONF.base + ":;{:.4f}".format(absolute_performance))
        else:
            part['mail'].append(
                "Overall performance in {}: {:>+10.4f} (% n/a)".format(CONF.base, absolute_performance))
            part['csv'].append("Overall performance in {}:;{:.4f}".format(CONF.base, absolute_performance))


def append_margin_change(part: dict, today: dict, currency: str):
    """
    Appends margin changes
    """
    formatter = 18.4 if currency == CONF.base else 16.2
    m_bal = "Margin balance " + currency + ": {:>{}f}".format(today['mBal'], formatter)
    if 'mBalChan24' in today:
        m_bal += " (" if currency == CONF.base else "   ({:+.2f}%)*".format(today['mBalChan24'])
    part['mail'].append(m_bal)
    formatter = .4 if currency == CONF.base else .2
    if 'mBalChan24' in today:
        part['csv'].append("Margin balance {}:;{:{}f};{:+.2f}%".format(currency, today['mBal'], formatter,
                                                                       today['mBalChan24']))
    else:
        part['csv'].append("Margin balance {}:;{:{}f};% n/a".format(currency, today['mBal'], formatter))


def append_price_change(part: dict, today: dict, price: float):
    """
    Appends price changes
    """
    rate = "{} price {}: {:>20.1f}".format(CONF.base, CONF.quote, price)
    if 'priceChan24' in today:
        rate += "    ({:+.2f}%)*".format(today['priceChan24'])
    part['mail'].append(rate)
    if 'priceChan24' in today:
        part['csv'].append("{} price {}:;{:.1f};{:+.2f}%".format(CONF.base, CONF.quote, price, today['priceChan24']))
    else:
        part['csv'].append("{} price {}:;{:.1f};% n/a".format(CONF.base, CONF.quote, price))


def calculate_all_sold_balance(poi: dict, sell_orders: [Order], margin_balance: float):
    if CONF.exchange == 'bitmex':
        sells = calculate_order_stats(sell_orders)
        tot_sell_quantity = float(sells['qty'])
        tot_sell_value = float(sells['val'])
        mark_price = float(poi['markPrice'])
        return (((tot_sell_quantity / (tot_sell_value * mark_price)) - 1) * tot_sell_value) + margin_balance
    return None


def calculate_price_offset(order_price: float, market_price: float):
    if order_price is not None:
        return round(abs(100 / (market_price / order_price) - 100), 2)
    return None


def write_csv(csv: str, filename_csv: str):
    if not is_already_written(filename_csv):
        if int(datetime.date.today().strftime("%j")) == 1:
            last_line = read_last_line(filename_csv)
            if last_line is not None:
                csv = last_line + csv
            write_mode = 'w'
        else:
            write_mode = 'a'
        with open(filename_csv, write_mode) as file:
            file.write(csv)


def is_already_written(filename_csv: str):
    last_line = read_last_line(filename_csv)
    if last_line is not None:
        return str(datetime.date.today().isoformat()) in last_line
    return False


def read_last_line(filename_csv: str):
    if os.path.isfile(filename_csv):
        with open(filename_csv, 'r') as file:
            return list(file)[-1]
    return None


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
    :return todays statistics including price and margin balance changes compared with 24 hours ago
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
    return today


def load_statistics():
    content = None
    stats_file = CONF.bot_instance + '.pkl'
    if os.path.isfile(stats_file):
        with open(stats_file, "rb") as file:
            content = pickle.load(file)
    return content


def persist_statistics():
    stats_file = CONF.bot_instance + '.pkl'
    with open(stats_file, "wb") as file:
        pickle.dump(STATS, file)


def read_moving_average():
    ma_file = 'maverage'
    if os.path.isfile(ma_file):
        with open(ma_file, "rt") as file:
            content = file.read()
        return content
    return None


def fetch_mayer(tries: int = 0):
    try:
        response = requests.get('https://mayermultiple.info/current.json')
        mayer = response.json()['data']
        return {'current': float(mayer['current_mayer_multiple']), 'average': float(mayer['average_mayer_multiple'])}

    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, requests.exceptions.ReadTimeout) as error:
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
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
    return None


def append_mayer(part: dict):
    text = print_mayer()
    if text is not None:
        part['mail'].append(text)
        part['csv'].append(text.replace('  ', '').replace('(', '').replace(')', '').replace(':', ':;').replace(' = ', ';'))
    else:
        part['mail'].append("Mayer multiple: {:>19}".format('n/a'))
        part['csv'].append("Mayer multiple:;n/a;n/a")


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
        leverage = round(get_leverage(), 1)
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
    else:
        set_leverage(CONF.leverage_default)


def get_target_leverage(mayer: dict):
    if CONF.auto_leverage:
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
        return None

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        get_leverage()


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
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        set_leverage(new_leverage)


def calculate_quota(price: float = None):
    margin_balance = get_margin_balance()['total']
    if margin_balance < 0:
        return 2
    if price is None:
        price = get_current_price()
    quota = round((math.sqrt(margin_balance * price) / 15) * 0.8 + (CONF.change * 200))
    return 2 if quota < 2 else 20 if quota > 20 else quota


def compact_position():
    """
    Optimizes a position by adjusting the leverage in order to maximize the used margin ratio and
    minimize the liquidation price
    """
    if calculate_used_margin_percentage() < 95:
        LOG.info('Compacting position')
        leverage = round(get_relevant_leverage(), 1)
        while set_leverage(round(leverage, 1)):
            sleep_for(0, 1)
            leverage -= 0.1


def deactivate_bot():
    os.remove(INSTANCE + '.pid')
    text = "Deactivated {}".format(INSTANCE)
    LOG.error(text)
    send_mail(text, text)
    exit(0)


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
            elif sys.argv[2] == '-pi':
                POSITION_INFO = True
    else:
        INSTANCE = os.path.basename(input('Filename with API Keys (config): ') or 'config')
    LOG_FILENAME = 'log' + os.path.sep + INSTANCE

    if not EMAIL_ONLY and not POSITION_INFO:
        write_control_file()

    if not os.path.exists('log'):
        os.makedirs('log')

    LOG = function_logger(logging.DEBUG, LOG_FILENAME, logging.INFO)
    LOG.info('----------------------------------')
    CONF = ExchangeConfig()
    LOG.info('Holdntrade version: %s', CONF.bot_version)
    EXCHANGE = connect_to_exchange()
    STATS = load_statistics()

    if EMAIL_ONLY:
        daily_report(True)
        exit(0)
    if POSITION_INFO:
        write_position_info(json.dumps(get_position_info(), indent=4))
        exit(0)

    LOOP = init_orders(False, AUTO_CONF)

    while True:
        if not SELL_ORDERS and CONF.stop_on_top and CONF.close_on_stop:
            HIBERNATE = True
        if not HIBERNATE:
            if LOOP:
                daily_report()
                buy_executed()
                sell_executed()
                if not SELL_ORDERS:
                    if not CONF.stop_on_top:
                        LOG.info('No sell orders, resetting all orders')
                        LOOP = init_orders(True, False)
                    else:
                        HIBERNATE = True
                        if CONF.stop_on_top and CONF.close_on_stop:
                            close_position(CONF.symbol)
                else:
                    spread(get_current_price())
            if not LOOP:
                adjust_leverage()
                compensate()
                if not CONF.stop_on_top:
                    if not INITIAL_LEVERAGE_SET:
                        INITIAL_LEVERAGE_SET = set_initial_leverage()
                    if not SELL_ORDERS:
                        create_first_sell_order()
                    if not BUY_ORDERS:
                        create_first_buy_order()
                LOG.info('Initialization complete')
                LOOP = True
        else:
            daily_report()
            LOG.info('Going to hibernate')
            sleep_for(600, 900)
            adjust_leverage()
            HIBERNATE = shall_hibernate()
