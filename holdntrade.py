#!/usr/bin/python
import configparser
import inspect
import os
import random
import sys
import time
from pprint import pprint

import ccxt

# ------------------------------------------------------------------------------

sell_price = 0
long_price = 0
curr_order = None
curr_sell = []
curr_order_size = 0
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


def trade_executed(price: float, amount: int, change: float):
    """
    Check if the most recent buy order has been executed.

    input: current price and amount to trade (Current Balance / divider)
    output: if the most recent buy order is still open,
    the output is print statements containing the amount were trying to buy for which price.
    Else if the order is closed, we follow with the followup function and createbuyorder and
    pass on the variables we got from input.
    """
    status = fetch_order_status()
    print('-------------------------------')
    print(what_time_is_it())
    if status == 'open':
        print('Open Buy Order! Amount: {} @ {}'.format(curr_order_size, long_price))
        print('Current Price: {}'.format(price))
    elif status in ['closed', 'canceled']:
        print('starting follow up')
        create_buy_order(price, amount, change)
        create_sell_order(change)
        print('Trade executed!')
    else:
        print('You should not be here\nOrder state: ' + status)


def sell_executed(price: float, amount: int, divider: int, change: float):
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
        status = fetch_sell_orders(orderId)
        if status == 'open':
            print('Sell still ' + status)
        elif status in ['closed', 'canceled']:
            curr_sell.remove(orderId)
            if len(curr_sell) == 0:
                create_divided_sell_order(divider, change)
            cancel_order()
            create_buy_order(price, amount, change)
            print('Sell executed')


def create_sell_order(change: float):
    """
    loop that starts after buy order is executed and sends sell order to exchange
    as well as appends the orderID to the sell_orders list.

    """
    global curr_sell
    global sell_price
    global curr_order_size

    try:
        if not is_order_below_limit(curr_order_size, sell_price):
            if conf.exchange == 'bitmex':
                order = exchange.create_limit_sell_order(conf.pair, curr_order_size, sell_price)
            elif conf.exchange == 'kraken':
                rate = get_current_price()
                order = exchange.create_limit_sell_order(conf.pair, curr_order_size/rate, sell_price)
            curr_sell.append(order['id'])
            pprint(order)

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        print('Got an error', type(error).__name__, error.args, ', retrying in about 5 seconds...')
        sell_price = round(get_current_price() * (1 + change))
        return create_sell_order(change)


def create_divided_sell_order(divider: float, change: float):
    """
    loop that starts after buy order is executed and sends sell order to exchange
    as well as appends the orderID to the sell_orders list.

    """
    global curr_sell
    global sell_price

    try:
        used_bal = get_used_balance()
        amount = round(used_bal / divider)

        if not is_order_below_limit(amount, sell_price):
            if conf.exchange == 'bitmex':
                order = exchange.create_limit_sell_order(conf.pair, amount, sell_price)
            elif conf.exchange == 'kraken':
                rate = get_current_price()
                order = exchange.create_limit_sell_order(conf.pair, amount/rate, sell_price)
            curr_sell.append(order['id'])
            pprint(order)

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        print('Got an error', type(error).__name__, error.args, ', retrying in about 5 seconds...')
        sell_price = round(get_current_price() * (1 + change))
        return create_divided_sell_order(divider, change)


def fetch_sell_orders(orderId: str):
    """
    fetch sell orders

    input: Order ID
    output: Status of the passed order with the passed orderID.
    """
    try:
        fo = exchange.fetch_order_status(orderId)

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        print('Got an error', type(error).__name__, error.args, ', retrying in about 5 seconds...')
        sleep_for(4, 6)
        return fetch_sell_orders(orderId)
    else:
        return fo


def fetch_order_status():
    """
    fetches the status of the current buy order

    output: status of order (open, closed)
    """
    try:
        fo = exchange.fetch_order_status(curr_order['id'])

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        print('Got an error', type(error).__name__, error.args, ', retrying in about 5 seconds...')
        sleep_for(4, 6)
        return fetch_order_status()
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
                print('Order to be canceled {0} was in state'.format(curr_order['id']), status)

    except (ccxt.OrderNotFound, ccxt.base.errors.OrderNotFound) as error:
        print('Order to be canceled not found', curr_order['id'], error.args)
        return
    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        print('Got an error', type(error).__name__, error.args, ', retrying in about 5 seconds...')
        sleep_for(4, 6)
        return cancel_order()


def create_buy_order(price: float, amount: int, change: float):
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

    long_price = round(price * (1 - change))
    sell_price = round(price * (1 + change))
    curr_order_size = amount
    cur_btc_price = get_current_price()

    try:
        if not is_order_below_limit(amount, long_price):
            if conf.exchange == 'bitmex':
                order = exchange.create_limit_buy_order(conf.pair, amount, long_price)
            elif conf.exchange == 'Kraken':
                order = exchange.create_limit_buy_order(conf.pair, amount/cur_btc_price, long_price)
            curr_order = order
            pprint(order)

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        print('Got an error', type(error).__name__, error.args, ', retrying in about 5 seconds...')
        sleep_for(4, 6)
        return create_buy_order(update_price(cur_btc_price, price), amount, change)


def create_first_order(price: float, amount: int, change: float):
    """
    creation of first order. Similar to createorder(price, amount) but with different price to go long.
    Calculated in raw USD, its the current price - the value of first_c
    """
    global long_price
    global sell_price
    global curr_sell
    global curr_order
    global curr_order_size

    cur_btc_price = get_current_price()

    long_price = round(price)
    sell_price = round(price * (1 + change))
    sell_amount = round(amount / 5)
    curr_order_size = sell_amount
    
    try:
        if conf.exchange == 'bitmex':
            order = exchange.create_market_buy_order(conf.pair, amount)
        elif conf.exchange == 'kraken':
            order = exchange.create_market_buy_order(conf.pair, amount/cur_btc_price)
        curr_order = order
        pprint(order)

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        print('Got an error', type(error).__name__, error.args, ', retrying in about 5 seconds...')
        sleep_for(4, 6)

        return create_first_order(update_price(cur_btc_price, price), amount, change)


def get_balance():
    """
    fetch the free balance in btc.

    output: balance
    """
    try:
        # syntax ok for bitmex and kraken
        bal = exchange.fetch_balance()['BTC']['free']

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        print('Got an error', type(error).__name__, error.args, ', retrying in about 5 seconds...')
        sleep_for(4, 6)
        return get_balance()
    else:
        return bal


def get_used_balance():
    """
    fetch the used balance in btc.

    output: balance
    """
    try:
        if conf.exchange == 'bitmex':
            used_bal = exchange.private_get_position()[0]['currentQty']
        elif conf.exchange == 'kraken':
            rate = get_current_price()
            used_bal = round(exchange.fetch_balance()['BTC']['used'] * rate)

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        print('Got an error', type(error).__name__, error.args, ', retrying in about 5 seconds...')
        sleep_for(4, 6)
        return get_used_balance()
    else:
        return used_bal


def get_current_price():
    """
    fetch the current BTC price

    output: last bid price
    """
    sleep_for(4, 6)
    try:
        d = exchange.fetch_ticker(conf.pair)

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        print('Got an error', type(error).__name__, error.args, ', retrying in about 5 seconds...')
        return get_current_price()
    else:
        price = d['bid']
        return price


def what_time_is_it():
    """
    output: current time at the exchange in seconds.
    """
    try:
        now = exchange.seconds()
        human = time.ctime(now)

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        print('Got an error', type(error).__name__, error.args, ', retrying in about 5 seconds...')
        sleep_for(4, 6)
        return what_time_is_it()
    else:
        return human


def update_price(origin_price: float, price: float):
    """
    update the price by considering the old and current price
    :param origin_price:
    :param price:
    :return: price
    """
    return (get_current_price() / origin_price) * price


def init_orders(change: float, divider: int, force_close: bool):
    """
    initialize existing orders or remove all pending ones
    output True if loaded and False if first order necessary
    :param change:
    :param divider:
    :param force_close:
    :return:
    """
    global curr_order
    global curr_sell
    global long_price
    global sell_price
    global curr_order_size

    buy_orders = []
    sell_orders = []

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
                    print(inspect.stack()[1][3], ' shit happens')
                    time.sleep(5)

            print("no. of buy orders : {0}".format(len(buy_orders)))
            print("no. of sell orders: {0}".format(len(sell_orders)))

            if not force_close or init.lower() in ['y', 'yes']:
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
                    sell_price = round(get_current_price() * (1 + change))
                    create_sell_order(change)

                # All buy orders executed
                elif 0 == len(buy_orders):
                    create_buy_order(get_current_price(), round(get_balance() / divider * get_current_price()), change)

                print('initialization complete (using existing orders)')
                # No "create first order" necessary
                return True

            else:
                print('Unrealised PNL: {0:.8f} BTC'.format(get_unrealised_pnl(conf.symbol) * conf.satoshi_factor))
                cancel = ''
                if not force_close:
                    cancel = input('All existing orders will be canceled! Are you sure (y/n)? ')
                if force_close or cancel.lower() in ['y', 'yes']:
                    cancel_orders(open_orders)
                    close_position(conf.symbol)
                else:
                    exit('')

        # Handle open positions if no orders are open
        elif not force_close and get_open_position(conf.symbol) is not None:
            msg = 'There is an open BTC position!\nUnrealised PNL: {0:.8f} BTC\nWould you like to close it? (y/n) '
            init = input(msg.format(get_unrealised_pnl(conf.symbol) * conf.satoshi_factor))
            if init.lower() in ['y', 'yes']:
                close_position(conf.symbol)

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        print('Got an error', type(error).__name__, error.args, ', retrying in about 5 seconds...')
        sleep_for(4, 6)
        return init_orders(change, divider, force_close)

    else:
        print('initialization complete')
        return False


def cancel_orders(orders):
    """
    Close a list of positions
    :param orders:
    :return:
    """
    try:
        for o in orders:
            print('cancel {0} order'.format(o['side']))

            status = exchange.fetch_order_status(o['id'])
            if status == 'open':
                exchange.cancel_order(o['id'])
            else:
                print('Cancel {0} order {1} was in state'.format(o['side'], o['id']), status)

    except (ccxt.OrderNotFound, ccxt.base.errors.OrderNotFound) as error:
        print('Cancel {0} order {1} not found'.format(o['side'], o['id']), error.args)
        return
    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        print('Got an error', type(error).__name__, error.args, ', retrying in about 5 seconds...')
        sleep_for(4, 6)
        return cancel_orders(orders)


def close_position(symbol: str):
    """
    Close any open position
    """
    try:
        print('close position ' + symbol)
        if conf.exchange == 'bitmex':
            exchange.private_post_order_closeposition({'symbol': symbol})
        elif conf.exchange == 'kraken':
            exchange.private_post_closepositions({'symbol': symbol})

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        print('Got an error', type(error).__name__, error.args, ', retrying in about 5 seconds...')
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
        print('Got an error', type(error).__name__, error.args, ', retrying in about 5 seconds...')
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
        print('Got an error', type(error).__name__, error.args, ', retrying in about 5 seconds...')
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
        #'verbose': True,
    })

    # pprint(dir(exchange))

    if hasattr(conf, 'test') & conf.test:
        if 'test' in exchange.urls:
            exchange.urls['api'] = exchange.urls['test']
        else:
            raise SystemExit('test not supported by ' + conf.exchange)

    print('connecting to', conf.exchange)
    return exchange


def sleep_for(greater: int, less: int):
    seconds = round(random.uniform(greater, less), 3)
    time.sleep(seconds)


def is_order_below_limit(amount: int, price: float):
    if abs(amount / price) < conf.order_btc_min:
        print('Per order volume below limit:', abs(amount / price))
        return True
    return False


def __exit__(msg: str):
    print(msg + '\nbot will stop in 5s.')
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

    conf = ExchangeConfig(filename)
    exchange = connect_to_exchange(conf)

    loop = init_orders(conf.change, conf.divider, False)

    while True:
        price = get_current_price()

        balance = get_balance()
        amount = round(balance / conf.divider * price)
        first_amount = round(balance / 2 * price)

        if is_order_below_limit(amount, price):
            print('Resetting all Orders')
            init_orders(conf.change, conf.divider, True)

        if loop:
            trade_executed(price, amount, conf.change)
            sell_executed(price, amount, conf.divider, conf.change)
            if len(curr_sell) == 0:
                print('No sell orders - resetting all Orders')
                init_orders(conf.change, conf.divider, True)
        else:
            create_first_order(price, first_amount, conf.change)
            loop = True
            print('-------------------------------')
            print(what_time_is_it())
            print('Created Buy Order over {}'.format(first_amount))

#
# V1.8.1 hello kraken
#
