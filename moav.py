#!/usr/bin/python
import configparser
import datetime
import inspect
import logging
import os
import pickle
from logging.handlers import RotatingFileHandler
from time import sleep

import ccxt


class ExchangeConfig:
    def __init__(self):

        config = configparser.RawConfigParser()
        config.read(CONF_NAME + ".txt")

        try:
            props = dict(config.items('config'))
            self.api_key = props['api_key'].strip('"')
            self.api_secret = props['api_secret'].strip('"')
            self.exchange = props['exchange'].strip('"').lower()
        except (configparser.NoSectionError, KeyError):
            raise SystemExit('Invalid configuration for ' + CONF_NAME)


class Stats:
    def __init__(self, day_of_year: int, data: dict):
        self.days = []
        self.add_day(day_of_year, data)

    def add_day(self, day_of_year: int, data: dict):
        existing = self.get_day(day_of_year)
        if existing is not None:
            total = existing['rate'] * existing['count']
            total_new = data['rate'] * data['count']
            data['rate'] = (total + total_new) / (existing['count'] + data['count'])
            data['count'] = existing['count'] + data['count']
            self.days.remove(existing)
        data['day'] = day_of_year
        if len(self.days) > 150:
            self.days = sorted(self.days, key=lambda dat: dat['day'], reverse=True)  # desc
            self.days.pop()
        self.days.append(data)

    def get_day(self, day_of_year: int):
        matched = filter(lambda element: element['day'] == day_of_year, self.days)
        if matched is not None:
            for day in matched:
                return day
        return None

    def get_ma(self, amount: int):
        self.days = sorted(self.days, key=lambda data: data['day'], reverse=True)
        scope = self.days[:amount]
        size = len(scope)
        if size != amount:
            LOG.warning('Not enough historical data, requested %d, found %d', amount, size)
        if int(datetime.date.today().strftime("%j")) >= size:
            if scope[-1]['day'] != int(datetime.date.today().strftime("%Y%j")) - (size - 1):
                LOG.warning('Incomplete historical data, earliest day requested %d, found %d',
                            int(datetime.date.today().strftime("%Y%j")) - (size - 1), scope[-1]['day'])
        else:
            if scope[-1]['day'] != int(datetime.date.today().strftime("%Y%j")) - (size - 1) - 635:
                LOG.warning('Incomplete historical data, earliest day requested %d, found %d',
                            int(datetime.date.today().strftime("%Y%j")) - (size - 1) - 635, scope[-1]['day'])
        avg = 0
        for day in scope:
            avg += day['rate']
        return round(avg / size)


def function_logger(console_level: int, filename: str, file_level: int = None):
    function_name = inspect.stack()[1][3]
    logger = logging.getLogger(function_name)
    # By default log all messages
    logger.setLevel(logging.DEBUG)

    # StreamHandler logs to console
    ch = logging.StreamHandler()
    ch.setLevel(console_level)
    ch.setFormatter(logging.Formatter('%(message)s'))
    logger.addHandler(ch)

    if file_level is not None:
        fh = RotatingFileHandler("{}.log".format(filename), mode='a', maxBytes=5 * 1024 * 1024, backupCount=4,
                                 encoding=None, delay=0)
        fh.setLevel(file_level)
        fh.setFormatter(logging.Formatter('%(asctime)s - %(lineno)4d - %(levelname)-8s - %(message)s'))
        logger.addHandler(fh)

    return logger


def load_history():
    if os.path.isfile(STATS_FILE):
        with open(STATS_FILE, "rb") as file:
            return pickle.load(file)
    return None


def persist_history(stats):
    with open(STATS_FILE, "wb") as file:
        pickle.dump(stats, file)


def update_history():
    stats = load_history()
    rate = get_current_price()
    if rate is not None:
        today = {'rate': rate, 'currency': 'USD', 'count': 1}
        stats.add_day(int(datetime.date.today().strftime("%Y%j")), today)
        persist_history(stats)
        return stats
    return None


def do_work():
    stats = update_history()
    parts = read_since()
    exit(0) if advise(stats, parts) else exit(1)


def advise(stats: Stats, parts: [str]):
    old_action = parts[0]
    since = parts[1].rstrip()
    if stats is not None:
        ma144 = stats.get_ma(144)
        ma21 = stats.get_ma(21)
        if ma144 > ma21:
            sign = '>'
            action = 'SELL'
        elif ma144 < ma21:
            sign = '<'
            action = 'BUY'
        else:
            sign = '='
            action = 'HOLD'
        if action != old_action:
            since = datetime.date.today().isoformat()
            write_since(action, since)
        advice = "{} {} {} = {} (since {})".format(ma144, sign, ma21, action, since)
        write_result(advice)
        LOG.info(advice)
        return True
    LOG.error('Unable to update advise')
    return False


def write_result(text: str):
    with open('maverage', 'wt') as file:
        file.write(text)


def read_since():
    if os.path.isfile(SINCE_FILE):
        with open(SINCE_FILE, "rt") as file:
            return file.read().split(' ')
    return ['SNAFU', '1929-10-25']


def write_since(action: str, date: str):
    with open(SINCE_FILE, "wt") as file:
        file.write(action + ' ' + date)


def connect_to_exchange():
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
    })
    return exchange


def get_current_price(tries: int = 0):
    if tries > 9:
        LOG.error('Failed fetching current price, giving up after 10 attempts')
        return None
    try:
        return EXCHANGE.fetch_ticker('BTC/USD')['bid']

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        LOG.debug('Got an error %s %s, retrying in 5 seconds...', type(error).__name__, str(error.args))
        sleep(5)
        get_current_price(tries+1)


if __name__ == "__main__":
    CONF_NAME = 'moav'
    SINCE_FILE = 'since'
    STATS_FILE = 'moav.pkl'

    LOG = function_logger(logging.DEBUG, CONF_NAME, logging.INFO)
    LOG.info('-------------------------------')
    CONF = ExchangeConfig()
    EXCHANGE = connect_to_exchange()

    do_work()
