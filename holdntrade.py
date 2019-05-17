import inspect
import sys
import time
import ccxt

PAIR = 'BTC/USD'
XBTC_SYMBOL = 'XBTUSD'
SATOSHI_FACTOR = 0.00000001

# ------------------------------------------------------------------------------

threshold = 25
sell_price = 0
long_price = 0
curr_order = None
curr_sell = []
curr_order_size = 0
loop = False
n = 0


# ------------------------------------------------------------------------------
        
def trade_executed(price, amount):
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
        create_buy_order(price, amount)
        create_sell_order()
        print('Trade executed!')
    else:
        print('You should not be here\nOrder state: ' + order)


def sell_executed(price, amount):
    """
    Check if any of the open sell orders has been executed.
    
    input: current price and amount to trade (Current Balance / divider)
    output: loop through all open sell orders and check if one has been executed. If no, exit with print statement.
    Else if it has been executed, remove the order from the list of open orders,
    cancel it on Bitmex and create a new buy order.
    """
    global curr_sell

    for o in curr_sell:
        time.sleep(0.3)
        status = fetch_sell_orders(o)
        if status == 'open':
            print('Sell still ' + status)
        elif status == 'closed':
            if len(curr_sell) == 1:
                create_divided_sell_order()
            curr_sell.remove(o)
            cancel_order()
            create_buy_order(price, amount)
            print('Sell executed')


def create_sell_order():
    """
    loop that starts after buy order is executed and sends sell order to exchange
    aswell as appends the orderID to the sell_orders list.
    
    """
    global curr_sell
    global sell_price

    try:
        order = exchange.create_order(PAIR, 'limit', 'sell', curr_order_size, sell_price)
        curr_sell.append(order['info']['orderID'])

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        print('Got an error', type(error).__name__, error.args, ', retrying in 5 seconds...')
        time.sleep(5)
        sell_price = round(get_current_price() * (1 + change))
        return create_sell_order()


def create_divided_sell_order():
    """
    loop that starts after buy order is executed and sends sell order to exchange
    aswell as appends the orderID to the sell_orders list.
    
    """
    global curr_sell
    global sell_price

    try:
        used_bal = get_used_balance()
        amount = round(used_bal / divider)
        order = exchange.create_order(PAIR, 'limit', 'sell', amount, sell_price)
        curr_sell.append(order['info']['orderID'])

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        print('Got an error', type(error).__name__, error.args, ', retrying in 5 seconds...')
        time.sleep(5)
        sell_price = round(get_current_price() * (1 + change))
        return create_divided_sell_order()


def fetch_sell_orders(order):
    """
    fetch sell orders
    
    input: Order ID
    output: Status of the passed order with the passed orderID. 
    """
    try:
        fo = exchange.fetchOrder(order)['status']

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        print('Got an error', type(error).__name__, error.args, ', retrying in 5 seconds...')
        time.sleep(5)
        return fetch_sell_orders(order)
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
        print('Got an error', type(error).__name__, error.args, ', retrying in 5 seconds...')
        time.sleep(5)
        return fetch_order()
    else:
        return fo


def cancel_order():
    """
    cancels the current order
    """
    try:
        exchange.cancel_order(curr_order['info']['orderID'])

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        print('Got an error', type(error).__name__, error.args, ', retrying in 5 seconds...')
        time.sleep(5)
        return cancel_order()


def create_buy_order(price, amount):
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
        order = exchange.create_order(PAIR, 'limit', 'buy', amount, long_price)
        curr_order = order
    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        print('Got an error', type(error).__name__, error.args, ', retrying in 5 seconds...')
        time.sleep(5)
        return create_buy_order(update_price(cur_btc_price, price), amount)


def create_first_order(price, amount):
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
        print('Got an error', type(error).__name__, error.args, ', retrying in 5 seconds...')
        time.sleep(5)

        return create_first_order(update_price(cur_btc_price, price), amount)


def get_balance():
    """
    fetch the free balance in btc.
    
    output: balance
    """
    try:
        bal = exchange.fetch_balance()['free']['BTC']

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        print('Got an error', type(error).__name__, error.args, ', retrying in 5 seconds...')
        time.sleep(5)
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
        print('Got an error', type(error).__name__, error.args, ', retrying in 5 seconds...')
        time.sleep(5)
        return get_used_balance()
    else:
        return used_bal


def get_current_price():
    """
    fetch the current BTC price
    
    output: last bid price
    """
    # time.sleep(1)
    try:
        d = exchange.fetch_ticker(PAIR)

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        print('Got an error', type(error).__name__, error.args, ', retrying in 5 seconds...')
        time.sleep(5)
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
        print('Got an error', type(error).__name__, error.args, ', retrying in 5 seconds...')
        time.sleep(5)
        return what_time_is_it()
    else:
        return human


def update_price(origin_price, price):
    """
    update the price by considering the old and current price
    :param origin_price:
    :param price:
    :return: price
    """
    return (get_current_price() / origin_price)*price


def init_orders(change, divider):
    """
    initialize existing orders or remove all pending ones
    output True if loaded and False if first order necessary
    :param carg:
    :param change:
    :param divider:
    :return:
    """
    global curr_order
    global curr_sell
    global long_price
    global sell_price
    global curr_order_size

    buy_orders = []
    sell_orders = []
    init = ''

    try:

        # Stop function
        if len(sys.argv) > 1 and sys.argv[1] == '-s':
            pnl = get_unrealised_pnl(XBTC_SYMBOL)
            cancel_orders(exchange.fetch_open_orders(PAIR, since=None, limit=None, params={}))
            close_position(XBTC_SYMBOL)
            exit('All orders sold\nUnrealised Pnl: {0:8f} BTC'.format(pnl * SATOSHI_FACTOR))

        # Handle open orders
        if len(exchange.fetch_open_orders(PAIR, since=None, limit=None, params={})):
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

            if init.lower() == 'y' or init.lower() == 'yes':
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
                    create_sell_order()

                # All buy orders executed
                elif 0 == len(buy_orders):
                    create_buy_order(get_current_price(), round(get_balance() / divider * get_current_price()))

                print('initialization complete')
                # No "create first order" necessary
                return True

            else:
                print('Unrealised PNL: {0:.8f} BTC'.format(
                    get_unrealised_pnl(XBTC_SYMBOL) * SATOSHI_FACTOR))
                cancel = input('All existing orders will be canceled! Are you sure (y/n)?')
                if cancel.lower() == 'y' or cancel.lower() == 'yes':
                    cancel_orders(open_orders)
                    close_position(XBTC_SYMBOL)
                else:
                    exit('')

        # Handle open positions if no orders are open
        else:
            if get_open_position(XBTC_SYMBOL) is not None:
                msg = 'There is an open BTC position!\nUnrealised PNL: {0:.8f} BTC\nWould you like to close it? (y/n)'
                init = input(msg.format(get_unrealised_pnl(XBTC_SYMBOL) * SATOSHI_FACTOR))
                if init.lower() == 'y' or init.lower() == 'yes':
                    close_position(XBTC_SYMBOL)

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        print('Got an error', type(error).__name__, error.args, ', retrying in 5 seconds...')
        time.sleep(5)
        return init_orders(change, divider)

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
        print('Got an error', type(error).__name__, error.args, ', retrying in 5 seconds...')
        time.sleep(5)
        return cancel_orders(orders)


def close_position(symbol):
    """
    Close any open position
    """
    try:
        print('close position ' + symbol)
        exchange.private_post_order_closeposition({'symbol': symbol})

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        print('Got an error', type(error).__name__, error.args, ', retrying in 5 seconds...')
        time.sleep(5)
        return close_position(symbol)


def get_open_position(symbol):
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
        print('Got an error', type(error).__name__, error.args, ', retrying in 5 seconds...')
        time.sleep(5)
        return get_open_position(symbol)


def get_unrealised_pnl(symbol):
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
        print('Got an error', type(error).__name__, error.args, ', retrying in 5 seconds...')
        time.sleep(5)
        return get_unrealised_pnl(symbol)
    

def connect_to_exchange(filename):
    """
    Imports the api_keys and secret from seperate .txt file aswell as the information if it should connect to the testnet or not.
    connects to the exchange.
    :param filename:
    :return: exchange
    """
    keys_file = open(filename+".txt")
    lines = keys_file.readlines()
    api_key = lines[0].split('"')[1]
    api_secret = lines[1].split('"')[1]
    test = lines[3].split('"')[1]
    
    if test == 'True':
        exchange = ccxt.bitmex({
        'enableRateLimit': True,
        'apiKey': api_key,
        'secret': api_secret,
        })
        if 'test' in exchange.urls:
            exchange.urls['api'] = exchange.urls['test']
    else:
        exchange = ccxt.bitmex({
        'enableRateLimit': True,
        'apiKey': api_key,
        'secret': api_secret,
        })
    return exchange


def __exit__(msg):
    print(msg + '\nbot will stop in 5s.')
    time.sleep(5)
    sys.exit()


# ------------------------------------------------------------------------------
if __name__ == '__main__':
    print('Starting Hold n Trade Bot')
    if sys.version_info[0] != 3:
        exit('Wrong python version!\nVersion 3.xx is needed')
    change = float(input("Define the change to enter a trade (0.005): "))
    divider = int(input("Define the divider to calculate the amount per trade (5): "))
    filename = input('Filename with API Keys: ')
    
    exchange = connect_to_exchange(filename)

    print('connecting to exchange')

    loop = init_orders(change, divider)

    while True:
        price = get_current_price()

        balance = get_balance()
        amount = round(balance / divider * price)
        first_amount = round(balance / 2 * price)
        
        if amount < int(threshold):
            #send-email / restart
            pass

        elif loop:
            trade_executed(price, amount)
            sell_executed(price, amount)

        else:
            create_first_order(price, first_amount)
            loop = True
            print('-------------------------------')
            print(what_time_is_it())
            print('Created Buy Order over {}'.format(first_amount))

        time.sleep(1)

#
# V1.4
#
