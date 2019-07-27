import unittest
from unittest import mock

import ccxt
import datetime
from unittest.mock import patch

import moav
from moav import Stats


class MoavTest(unittest.TestCase):

    @patch('moav.logging')
    def test_stats_add_same_day(self, mock_logging):
        moav.log = mock_logging
        today = {'rate': 10000.00, 'currency': 'USD', 'count': 1}
        stats = Stats(int(datetime.date.today().strftime("%Y%j")), today)
        same_day = {'rate': 5000.00, 'currency': 'USD', 'count': 1}

        stats.add_day(int(datetime.date.today().strftime("%Y%j")), same_day)

        day = stats.get_day(int(datetime.date.today().strftime("%Y%j")))
        self.assertTrue(day['count'] == 2)
        self.assertTrue(day['rate'] == 7500.00)

    @patch('moav.logging')
    def test_stats_add_same_day_weighted(self, mock_logging):
        moav.log = mock_logging
        today = {'rate': 10000.00, 'currency': 'USD', 'count': 2}
        stats = Stats(int(datetime.date.today().strftime("%Y%j")), today)
        same_day = {'rate': 5000.00, 'currency': 'USD', 'count': 1}

        stats.add_day(int(datetime.date.today().strftime("%Y%j")), same_day)

        day = stats.get_day(int(datetime.date.today().strftime("%Y%j")))
        self.assertTrue(day['count'] == 3)
        self.assertTrue(round(day['rate']) == 8333)

    @patch('moav.logging')
    def test_stats_get_ma(self, mock_logging):
        moav.log = mock_logging
        today = {'rate': 10000.00, 'currency': 'USD', 'count': 1}
        stats = Stats(int(datetime.date.today().strftime("%Y%j")), today)
        another_day = {'rate': 5000.00, 'currency': 'USD', 'count': 1}
        stats.add_day(int(datetime.date.today().strftime("%Y%j")) - 1, another_day)

        stats.get_ma(2)

        self.assertTrue(stats.get_ma(2) == 7500.00)

    @patch('moav.logging')
    def test_stats_get_ma_not_enough_data(self, mock_logging):
        moav.log = mock_logging
        today = {'rate': 10000.00, 'currency': 'USD', 'count': 1}
        stats = Stats(int(datetime.date.today().strftime("%Y%j")), today)
        same_day = {'rate': 5000.00, 'currency': 'USD', 'count': 1}
        stats.add_day(int(datetime.date.today().strftime("%Y%j")), same_day)

        stats.get_ma(2)

        mock_logging.warning.assert_called_with('Not enough historical data, requested %d, found %d', 2, 1)
        self.assertTrue(stats.get_ma(2) == 7500.00)

    @patch('moav.logging')
    def test_stats_get_ma_not_incomplete_data(self, mock_logging):
        moav.log = mock_logging
        today = {'rate': 10000.00, 'currency': 'USD', 'count': 1}
        stats = Stats(int(datetime.date.today().strftime("%Y%j")), today)
        same_day = {'rate': 5000.00, 'currency': 'USD', 'count': 1}
        stats.add_day(int(datetime.date.today().strftime("%Y%j")) - 2, same_day)
        earliest_day = int(datetime.date.today().strftime("%Y%j")) - 1

        stats.get_ma(2)

        mock_logging.warning.assert_called_with('Incomplete historical data, earliest day requested %d, found %d',
                                                earliest_day, earliest_day - 1)
        self.assertTrue(stats.get_ma(2) == 7500.00)

    @patch('moav.write_result')
    @patch('moav.Stats')
    @patch('moav.logging')
    def test_advise_with_same_result(self, mock_logging, mock_stats, mock_write_result):
        moav.log = mock_logging
        return_values = {144: 10000, 21: 8000}
        mock_stats.get_ma.side_effect = return_values.get
        parts = ['SELL', '2016-11-22']

        moav.advise(mock_stats, parts)

        mock_write_result.assert_called_with("10000 > 8000 = SELL (since 2016-11-22)")

    @patch('moav.write_result')
    @patch('moav.Stats')
    @patch('moav.logging')
    def test_advise_with_new_result(self, mock_logging, mock_stats, mock_write_result):
        moav.log = mock_logging
        today = datetime.date.today().isoformat()
        return_values = {144: 7999, 21: 8000}
        mock_stats.get_ma.side_effect = return_values.get
        parts = ['SELL', '2016-11-22']

        moav.advise(mock_stats, parts)

        mock_write_result.assert_called_with("7999 < 8000 = BUY (since {})".format(today))

    @mock.patch.object(ccxt.bitmex, 'fetch_ticker')
    @patch('moav.logging')
    def test_get_current_price(self, mock_logging, mock_fetch_ticker):
        moav.conf = self.create_default_conf()
        moav.log = mock_logging
        moav.exchange = moav.connect_to_exchange(moav.conf)
        market_price = 9000
        mock_fetch_ticker.return_value = {'bid': market_price}

        price = moav.get_current_price()

        mock_fetch_ticker.assert_called()
        self.assertTrue(price == market_price)

    @staticmethod
    def create_default_conf():
        conf = moav.ExchangeConfig
        conf.exchange = 'bitmex'
        conf.api_key = '1234'
        conf.api_secret = 'secret'
        return conf

    if __name__ == '__main__':
        unittest.main()
