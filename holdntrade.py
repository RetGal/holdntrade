#!/usr/bin/python
import configparser
import inspect
import os
import random
import sys
import time
import ccxt

PAIR = 'BTC/USD'
XBTC_SYMBOL = 'XBTUSD'
SATOSHI_FACTOR = 0.00000001

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
    order = fetch_order()
    print('-------------------------------')
    print(what_time_is_it())
    if order == 'open':
        print('Open Buy Order! Amount: {} @ {}'.format(curr_order_size, long_price))
        print('Current Price: {}'.format(price))
    elif order == 'closed':
        print('starting follow up')
        create_buy_order(price, amount, change)
        create_sell_order(change)
        print('Trade executed!')
    else:
        print('You should not be here\nOrder state: ' + order)


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
        elif status == 'closed':
            if len(curr_sell) == 1:
                create_divided_sell_order(divider, change)
            curr_sell.remove(orderId)
            curr_order = cancel_order(curr_order)
            create_buy_order(price, amount, change)
            print('Sell executed')


def create_sell_order(change: float):
    """
    loop that starts after buy order is executed and sends sell order to exchange
    as well as appends the orderID to the sell_orders list.

    """
    global curr_sell
    global sell_price

    try:
        if not is_order_below_limit(curr_order_size, sell_price):
            order = exchange.create_order(PAIR, 'limit', 'sell', curr_order_size, sell_price)
            curr_sell.append(order['info']['orderID'])

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        print('Got an error', type(error).__name__, error.args, ', retrying in about 5 seconds...')
        # sleep_for(4, 6)
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
            order = exchange.create_order(PAIR, 'limit', 'sell', amount, sell_price)
            curr_sell.append(order['info']['orderID'])

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        print('Got an error', type(error).__name__, error.args, ', retrying in about 5 seconds...')
        # sleep_for(4, 6)
        sell_price = round(get_current_price() * (1 + change))
        return create_divided_sell_order(divider, change)


def fetch_sell_orders(orderId: str):
    """
    fetch sell orders

    input: Order ID
    output: Status of the passed order with the passed orderID.
    """
    try:
        fo = exchange.fetchOrder(orderId)['status']

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        print('Got an error', type(error).__name__, error.args, ', retrying in about 5 seconds...')
        sleep_for(4, 6)
        return fetch_sell_orders(orderId)
    else:
        return fo


def fetch_order():
    """
    fetches the status of the current buy order

    output: status of order (open, closed)
    """
    try:
        fo = exchange.fetchOrder(curr_order['info']['orderID'])['status']

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        print('Got an error', type(error).__name__, error.args, ', retrying in about 5 seconds...')
        sleep_for(4, 6)
        return fetch_order()
    else:
        return fo


def cancel_order(order):
    """
    cancels the current order
    """
    try:
        if hasattr(order, 'info'):
            print('cancel order', order['info']['orderID'])
            exchange.cancel_order(order['info']['orderID'])
        return None

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        print('Got an error', type(error).__name__, error.args, ', retrying in about 5 seconds...')
        sleep_for(4, 6)
        return cancel_order(order)


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
    global order_btc_min

    long_price = round(price * (1 - change))
    sell_price = round(price * (1 + change))
    curr_order_size = amount
    cur_btc_price = get_current_price()

    try:
        if not is_order_below_limit(amount, long_price):
            order = exchange.create_order(PAIR, 'limit', 'buy', amount, long_price)
            curr_order = order
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
        order = exchange.create_order(PAIR, 'market', 'buy', amount)
        curr_order = order
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
        bal = exchange.fetch_balance()['free']['BTC']

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
        used_bal = exchange.private_get_position()[0]['currentQty']

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
        d = exchange.fetch_ticker(PAIR)

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        print('Got an error', type(error).__name__, error.args, ', retrying in about 5 seconds...')
        # sleep_for(4, 6)
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
        # Stop function
        if len(sys.argv) > 1 and sys.argv[1] == '-s':
            pnl = get_unrealised_pnl(XBTC_SYMBOL)
            cancel_orders(exchange.fetch_open_orders(PAIR, since=None, limit=None, params={}))
            close_position(XBTC_SYMBOL)
            exit('All orders sold\nUnrealised Pnl: {0:8f} BTC'.format(pnl * SATOSHI_FACTOR))

        # Handle open orders
        if len(exchange.fetch_open_orders(PAIR, since=None, limit=None, params={})):
            if not force_close:
                init = input('There are open orders! Would you like to load them? (y/n)')

            open_orders = exchange.fetch_open_orders(symbol=PAIR, since=None, limit=None, params={})
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
                    curr_sell.append(o['info']['orderID'])

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

                print('initialization complete')
                # No "create first order" necessary
                return True

            else:
                print('Unrealised PNL: {0:.8f} BTC'.format(get_unrealised_pnl(XBTC_SYMBOL) * SATOSHI_FACTOR))
                cancel = ''
                if not force_close:
                    cancel = input('All existing orders will be canceled! Are you sure (y/n)?')
                if force_close or cancel.lower() in ['y', 'yes']:
                    cancel_orders(open_orders)
                    close_position(XBTC_SYMBOL)
                else:
                    exit('')

        # Handle open positions if no orders are open
        else:
            if get_open_position(XBTC_SYMBOL) is not None:
                msg = 'There is an open BTC position!\nUnrealised PNL: {0:.8f} BTC\nWould you like to close it? (y/n)'
                init = input(msg.format(get_unrealised_pnl(XBTC_SYMBOL) * SATOSHI_FACTOR))
                if init.lower() in ['y', 'yes']:
                    close_position(XBTC_SYMBOL)

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
            exchange.cancel_order(o['info']['orderID'])

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
        exchange.private_post_order_closeposition({'symbol': symbol})

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
        for p in exchange.private_get_position():
            if p['isOpen'] and p['symbol'] == symbol:
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
    })

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

    global order_btc_min

    if amount / price < order_btc_min:
        print('Per order volume below limit:', amount / price)
        return True
    return False


def __exit__(msg: str):
    print(msg + '\nbot will stop in 5s.')
    time.sleep(5)
    sys.exit()


# ------------------------------------------------------------------------------
if __name__ == '__main__':
    print('Starting Hold n Trade Bot')
    if sys.version_info[0] != 3:
        exit('Wrong python version!\nVersion 3.xx is needed')
    filename = os.path.basename(input('Filename with API Keys (config): ') or 'config')

    conf = ExchangeConfig(filename)
    exchange = connect_to_exchange(conf)
    order_btc_min = conf.order_btc_min

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
            if len(curr_sell) > 0:
                trade_executed(price, amount, conf.change)
                sell_executed(price, amount, conf.divider, conf.change)
            else:
                print('No sell orders - resetting all Orders')
                init_orders(conf.change, conf.divider, True)
        else:
            create_first_order(price, first_amount, conf.change)
            loop = True
            print('-------------------------------')
            print(what_time_is_it())
            print('Created Buy Order over {}'.format(first_amount))

#
# V1.6.7 fixed sell order removal
#
