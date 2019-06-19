#!/usr/bin/python
import configparser
import inspect
import logging
import os
import random
import sys
import time
from logging.handlers import RotatingFileHandler

import ccxt

# ------------------------------------------------------------------------------

sell_price = 0
long_price = 0
curr_order = None
curr_sell = []
curr_order_size = 0
reset_counter = 0
loop = False
n = 0

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
            self.exchange = props['exchange'].strip('"').lower()
            self.api_key = props['api_key'].strip('"')
            self.api_secret = props['api_secret'].strip('"')
            self.test = bool(props['test'].strip('"').lower() == 'true')
            self.pair = props['pair'].strip('"')
            self.symbol = props['symbol'].strip('"')
            self.satoshi_factor = float(props['satoshi_factor'].strip('"'))
            self.change = float(props['change'].strip('"'))
            self.divider = int(props['divider'].strip('"'))
            self.order_btc_min = float(props['order_btc_min'].strip('"'))
        except (configparser.NoSectionError, KeyError):
            raise SystemExit('invalid configuration for ' + filename)


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
    global curr_order_size

    if curr_order is None:
        status = 'closed'
        log.info('Closed inexisting compensation order')
    else:
        status = fetch_order_status(curr_order['id'])
    log.debug('-------------------------------')
    log.debug(time.ctime())
    if status == 'open':
        log.debug('Open Buy Order! Amount: {} @ {}'.format(curr_order_size, long_price))
        log.debug('Current Price: {}'.format(price))
    elif status in ['closed', 'canceled']:
        log.info('Trade executed, starting follow up')
        last_buy_size = curr_order_size
        create_buy_order(price, amount)
        create_sell_order(last_buy_size)
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
    global curr_sell
    global curr_order

    for orderId in curr_sell:
        time.sleep(0.5)
        status = fetch_order_status(orderId)
        if status == 'open':
            log.debug('Sell still ' + status)
        elif status in ['closed', 'canceled']:
            curr_sell.remove(orderId)
            log.info('Sell executed')
            if len(curr_sell) == 0:
                create_divided_sell_order()
            cancel_order()
            create_buy_order(price, amount)
        else:
            log.warning('You should not be here, order state: ' + status)


def create_sell_order(fixed_order_size: int = None):
    """
    loop that starts after buy order is executed and sends sell order to exchange
    as well as appends the orderID to the sell_orders list.

    """
    global curr_sell
    global sell_price
    global curr_order_size

    if fixed_order_size is None:
        order_size = curr_order_size
    else:
        order_size = fixed_order_size

    stock = get_used_balance()
    if stock < order_size:
        # sold out - the main loop will re-init if there are no other sell orders open
        log.warning('Not executing sell order over {0} (only {1} left)'.format(str(order_size), str(stock)))
        return

    try:
        if not is_order_below_limit(order_size, sell_price):
            if conf.exchange == 'bitmex':
                order = exchange.create_limit_sell_order(conf.pair, order_size, sell_price)
            elif conf.exchange == 'kraken':
                rate = get_current_price()
                order = exchange.create_limit_sell_order(conf.pair, to_kraken(order_size, rate), sell_price, {'leverage': 2})
            curr_sell.append(order['id'])
            log.info(str(order))

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
    loop that starts after buy order is executed and sends sell order to exchange
    as well as appends the orderID to the sell_orders list.

    """
    global curr_sell
    global sell_price

    try:
        used_bal = get_used_balance()
        amount = round(used_bal / conf.divider)

        if not is_order_below_limit(amount, sell_price):
            if conf.exchange == 'bitmex':
                order = exchange.create_limit_sell_order(conf.pair, amount, sell_price)
            elif conf.exchange == 'kraken':
                rate = get_current_price()
                order = exchange.create_limit_sell_order(conf.pair, to_kraken(amount, rate), sell_price, {'leverage': 2})
            curr_sell.append(order['id'])
            log.info(str(order))

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
    fetches the status of an order

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


def cancel_order():
    """
    cancels the current order
    """
    global curr_order

    try:
        if curr_order is not None:
            status = exchange.fetch_order_status(curr_order['id'])
            if status == 'open':
                exchange.cancel_order(curr_order['id'])
            else:
                log.warning('Order to be canceled {0} was in state '.format(curr_order['id']) + status)

    except (ccxt.OrderNotFound, ccxt.base.errors.OrderNotFound) as error:
        log.error('Order to be canceled not found ' + curr_order['id'] + error.args)
        return
    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        log.error('Got an error ' + type(error).__name__ + str(error.args) + ', retrying in about 5 seconds...')
        sleep_for(4, 6)
        return cancel_order()


def create_buy_order(price: float, amount: int):
    """
    creates a buy order and sets the values as global ones. Used by other functions.

    input: current price of BTC and 1/divider of balance.
    output: calculate the price to get long (price + change) and to get short (price - change).
    In addition set the current orderID and current order size as global values.
    """
    global long_price
    global sell_price
    global curr_order
    global curr_order_size
    global reset_counter

    long_price = round(price * (1 - conf.change))
    sell_price = round(price * (1 + conf.change))
    curr_order_size = amount
    cur_btc_price = get_current_price()

    try:
        if not is_order_below_limit(amount, long_price):
            if conf.exchange == 'bitmex':
                order = exchange.create_limit_buy_order(conf.pair, amount, long_price)
            elif conf.exchange == 'kraken':
                order = exchange.create_limit_buy_order(conf.pair, to_kraken(amount, cur_btc_price), long_price, {'leverage': 2})
            curr_order = order
            log.info(str(order))

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        # insufficient margin
        if "nsufficient" in str(error.args):
            log.error('Insufficient initial margin - not buying ' + str(amount))
            return
        elif "too low" in str(error.args):
            log.error('Margin level too low - not buying ' + str(amount))
            return
        log.error('Got an error ' + type(error).__name__ + str(error.args) + ', retrying in about 5 seconds...')
        sleep_for(4, 6)
        return create_buy_order(update_price(cur_btc_price, price), amount)

    if reset_counter > 0:
        reset_counter -= 1


def create_market_sell_order(amount_btc: float):
    """
    creates a market sell order and sets the values as global ones. Used to compensate margins above 50%.

    input: amount_btc to be sold to reach 50% margin
    """
    global long_price
    global sell_price
    global curr_sell

    cur_btc_price = get_current_price()

    amount = round(amount_btc*cur_btc_price)

    long_price = round(cur_btc_price * (1 - conf.change))
    sell_price = round(cur_btc_price * (1 + conf.change))

    try:
        if not is_btc_amount_below_limit(amount_btc):
            if conf.exchange == 'bitmex':
                order = exchange.create_market_sell_order(conf.pair, amount)
            elif conf.exchange == 'kraken':
                order = exchange.create_market_sell_order(conf.pair, amount_btc, {'leverage': 2})
            curr_sell.append(order['id'])
            log.info(str(order))

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
    creates a market buy order and sets the values as global ones. Used to compensate margins below 50%.

    input: amount_btc to be bought to reach 50% margin
    """

    global long_price
    global sell_price
    global curr_order

    cur_btc_price = get_current_price()

    amount = round(amount_btc*cur_btc_price)

    long_price = round(cur_btc_price * (1 - conf.change))
    sell_price = round(cur_btc_price * (1 + conf.change))

    try:
        if not is_order_below_limit(amount, cur_btc_price):
            if conf.exchange == 'bitmex':
                order = exchange.create_market_buy_order(conf.pair, amount)
            elif conf.exchange == 'kraken':
                order = exchange.create_market_buy_order(conf.pair, amount_btc, {'leverage': 2})
            curr_order = order
            log.info(str(order))

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        log.error('Got an error ' + type(error).__name__ + str(error.args) + ', retrying in about 5 seconds...')
        sleep_for(4, 6)
        return create_market_buy_order(amount_btc)


def get_balance():
    """
    fetch the free balance in btc.

    output: balance
    """
    try:
        return exchange.fetch_balance()['BTC']['free']

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        log.error('Got an error' + type(error).__name__ + str(error.args) + ', retrying in about 5 seconds...')
        sleep_for(4, 6)
        return get_balance()


def get_used_balance():
    """
    fetch the used balance in btc.

    output: balance
    """
    try:
        if conf.exchange == 'bitmex':
            return exchange.private_get_position()[0]['currentQty']
        elif conf.exchange == 'kraken':
            result = exchange.private_post_tradebalance()['result']
            return round(float(result['e']) - float(result['mf']))

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        log.error('Got an error ' + type(error).__name__ + str(error.args) + ', retrying in about 5 seconds...')
        sleep_for(4, 6)
        return get_used_balance()


def compensate():
    """
    approaches the margin used towards 50% by selling or buying the difference to market price

    """
    try:
        bal = exchange.fetch_balance()['BTC']

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        log.error('Got an error' + type(error).__name__ + str(error.args) + ', retrying in about 5 seconds...')
        sleep_for(4, 6)
        return compensate()

    used = float(100-(bal['free']/bal['total'])*100)
    if used < 40 or used > 60:
        amount_btc = float(bal['total']/2-bal['used'])
        if amount_btc > 0:
            log.info("Need to buy {0} BTC in order to reach 50% margin".format(amount_btc))
            create_market_buy_order(amount_btc)
        else:
            log.info("Need to sell {0} BTC in order to reach 50% margin".format(abs(amount_btc)))
            create_market_sell_order(abs(amount_btc))
    return


def get_current_price():
    """
    fetch the current BTC price

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
    update the price by considering the old and current price
    :param origin_price:
    :param price:
    :return: price
    """
    return (get_current_price() / origin_price) * price


def init_orders(force_close: bool):
    """
    initialize existing orders or remove all pending ones
    output True if loaded and False if first order necessary
    :param force_close: close all orders/positions (reset)
    :return:
    """
    global curr_order
    global curr_sell
    global long_price
    global sell_price
    global curr_order_size
    global reset_counter

    buy_orders = []
    sell_orders = []

    reset_counter += 5

    try:
        init = ''
        # Handle open orders
        open_orders = exchange.fetch_open_orders(conf.pair, since=None, limit=None, params={})
        if len(open_orders):
            if not force_close:
                init = input('There are open orders! Would you like to load them? (y/n) ')

            for o in open_orders:
                if o['side'] == 'sell':
                    sell_orders.append(o)
                elif o['side'] == 'buy':
                    buy_orders.append(o)
                else:
                    log.error(inspect.stack()[1][3], ' shit happens')
                    time.sleep(5)

            log.info("no. of buy orders : {0}".format(len(buy_orders)))
            log.info("no. of sell orders: {0}".format(len(sell_orders)))

            if force_close is False and init.lower() in ['y', 'yes']:
                sell_orders = sorted(sell_orders, key=lambda o: o['price'], reverse=True)

                for o in sell_orders:
                    sell_price = o['price']
                    curr_sell.append(o['id'])

                for o in buy_orders:
                    long_price = o['price']
                    curr_order = o
                    curr_order_size = o['amount']

                # All sell orders executed
                if 0 == len(sell_orders):
                    sell_price = round(get_current_price() * (1 + conf.change))
                    create_sell_order()

                # All buy orders executed
                elif 0 == len(buy_orders):
                    create_buy_order(get_current_price(), round(get_balance() / conf.divider * get_current_price()))

                log.info('initialization complete (using existing orders)')
                # No "create first order" / "approach_half_margin" necessary
                return True

            else:
                log.info('Unrealised PNL: {0:.8f} BTC'.format(get_unrealised_pnl(conf.symbol) * conf.satoshi_factor))
                cancel = ''
                if force_close is False:
                    cancel = input('All existing orders will be canceled! Are you sure (y/n)? ')
                if force_close or cancel.lower() in ['y', 'yes']:
                    cancel_orders(open_orders)
                    if reset_counter > 9:
                        log.warning('Closing position, reset counter is ' + str(reset_counter))
                        reset_counter = 0
                        close_position(conf.symbol)

        # Handle open positions if no orders are open
        elif force_close is False and get_open_position(conf.symbol) is not None:
            msg = 'There is an open BTC position!\nUnrealised PNL: {0:.8f} BTC\nWould you like to close it? (y/n) '
            init = input(msg.format(get_unrealised_pnl(conf.symbol) * conf.satoshi_factor))
            if init.lower() in ['y', 'yes']:
                close_position(conf.symbol)

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        log.error('Got an error ' + type(error).__name__ + str(error.args) + ', retrying in about 5 seconds...')
        sleep_for(4, 6)
        return init_orders(force_close)

    else:
        log.info('initialization complete')
        return False


def cancel_orders(orders):
    """
    Close a list of positions
    :param orders:
    :return:
    """
    try:
        for o in orders:
            log.debug('cancel {0} order'.format(o['side']))

            status = exchange.fetch_order_status(o['id'])
            if status == 'open':
                exchange.cancel_order(o['id'])
            else:
                log.warnig('Cancel {0} order {1} was in state '.format(o['side'], o['id']) + status)

    except (ccxt.OrderNotFound, ccxt.base.errors.OrderNotFound) as error:
        log.error('Cancel {0} order {1} not found '.format(o['side'], o['id']) + error.args)
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
        if conf.exchange == 'bitmex':
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
        if conf.exchange == 'bitmex':
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
    exchanges = {'bitmex': ccxt.bitmex,
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
            raise SystemExit('test not supported by ' + conf.exchange)

    log.info('connecting to ' + conf.exchange)
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


def __exit__(msg: str):
    log.info(msg + '\nbot will stop in 5s.')
    time.sleep(5)
    sys.exit()


# ------------------------------------------------------------------------------
if __name__ == '__main__':
    print('Starting Hold n Trade Bot')
    print('ccxt version:', ccxt.__version__)
    if sys.version_info[0] != 3:
        exit('Wrong python version!\nVersion 3.xx is needed')

    if len(sys.argv) > 1:
        filename = os.path.basename(sys.argv[1])
    else:
        filename = os.path.basename(input('Filename with API Keys (config): ') or 'config')

    log = function_logger(logging.DEBUG, filename, logging.INFO)
    log.info('-------------------------------')

    conf = ExchangeConfig(filename)
    exchange = connect_to_exchange(conf)

    loop = init_orders(False)

    while True:
        price = get_current_price()

        balance = get_balance()
        amount = round(balance / conf.divider * price)

        if is_order_below_limit(amount, price):
            log.info('Resetting all Orders')
            init_orders(True)

        if loop:
            trade_executed(price, amount)
            sell_executed(price, amount)
            if len(curr_sell) == 0:
                log.info('No sell orders - resetting all Orders')
                init_orders(True)
        else:
            # good enough as starting point if no compensation buy/sell is required
            curr_order_size = amount
            compensate()
            loop = True

#
# V1.9.7 reset_counter log fixed
#
