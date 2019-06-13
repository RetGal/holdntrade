import time
import unittest
from unittest import mock
from unittest.mock import patch

import ccxt

import holdntrade


class HoldntradeTest(unittest.TestCase):

    @patch('holdntrade.logging')
    def test_connect_to_exchange_params_bitmex(self, mock_logging):
        holdntrade.log = mock_logging
        conf = holdntrade.ExchangeConfig
        conf.exchange = 'bitmex'
        conf.api_key = 'key'
        conf.api_secret = 'secret'
        conf.test = True

        exchange = holdntrade.connect_to_exchange(conf)

        self.assertEqual(exchange.id, conf.exchange)
        self.assertEqual(exchange.apiKey, conf.api_key)
        self.assertEqual(exchange.secret, conf.api_secret)
        self.assertEqual(exchange.urls['api'], exchange.urls['test'])

    @patch('holdntrade.logging')
    def test_connect_to_exchange_params_kraken(self, mock_logging):
        holdntrade.log = mock_logging
        conf = holdntrade.ExchangeConfig
        conf.exchange = 'kraken'
        conf.api_key = 'key'
        conf.api_secret = 'secret'
        conf.test = False

        exchange = holdntrade.connect_to_exchange(conf)

        self.assertEqual(exchange.id, conf.exchange)
        self.assertEqual(exchange.apiKey, conf.api_key)
        self.assertEqual(exchange.secret, conf.api_secret)

    @patch('holdntrade.logging')
    def test_connect_to_exchange_params_liquid(self, mock_logging):
        holdntrade.log = mock_logging
        conf = holdntrade.ExchangeConfig
        conf.exchange = 'liquid'
        conf.api_key = 'key'
        conf.api_secret = 'secret'
        conf.test = False

        exchange = holdntrade.connect_to_exchange(conf)

        self.assertEqual(exchange.id, conf.exchange)
        self.assertEqual(exchange.apiKey, conf.api_key)
        self.assertEqual(exchange.secret, conf.api_secret)

    @patch('holdntrade.logging')
    def test_connect_to_exchange_should_fail_if_param_test_is_true_but_not_supported(self, mock_logging):
        holdntrade.log = mock_logging
        conf = holdntrade.ExchangeConfig
        conf.exchange = 'kraken'
        conf.api_key = 'key'
        conf.api_secret = 'secret'
        conf.test = True

        with self.assertRaises(SystemExit) as context:
            holdntrade.connect_to_exchange(conf)

        self.assertTrue('test not supported' in str(context.exception))

    @patch('holdntrade.logging')
    def test_connect_to_exchange_should_fail_if_exchange_not_supported(self, mock_logging):
        holdntrade.log = mock_logging
        conf = holdntrade.ExchangeConfig
        conf.exchange = 'unknown'
        conf.api_key = 'key'
        conf.api_secret = 'secret'
        conf.test = False

        with self.assertRaises(Exception) as context:
            holdntrade.connect_to_exchange(conf)

        self.assertTrue('unknown' in str(context.exception))

    def test_sleep_for(self):
        before = time.time()

        holdntrade.sleep_for(1, 3)

        after = time.time()
        diff = after - before
        self.assertGreater(diff, 1, 'Should have slept for more than 1 second, but did not')
        self.assertLessEqual(diff, 3, 'Should have slept for less than 3 seconds, but did not')

    def test_is_order_below_limit_true(self):
        price = 8000
        amount = 10
        holdntrade.conf = self.create_default_conf()

        self.assertTrue(holdntrade.is_order_below_limit(amount, price))

    def test_is_order_negative_amount_below_limit_true(self):
        price = 8000
        amount = -10
        holdntrade.conf = self.create_default_conf()

        self.assertTrue(holdntrade.is_order_below_limit(amount, price))

    def test_is_order_below_limit_false(self):
        price = 4000
        amount = 10
        holdntrade.conf = self.create_default_conf()

        self.assertFalse(holdntrade.is_order_below_limit(amount, price))

    def test_is_order_negative_amount_below_limit_false(self):
        price = 4000
        amount = -10
        holdntrade.conf = self.create_default_conf()

        self.assertFalse(holdntrade.is_order_below_limit(amount, price))

    @patch('holdntrade.logging')
    @mock.patch.object(ccxt.bitmex, 'create_limit_sell_order')
    def test_create_sell_order_should_not_create_order_if_order_is_below_limit(self, mock_create_limit_sell_order,
                                                                               mock_logging):
        holdntrade.sell_price = 8000
        holdntrade.curr_sell = []
        holdntrade.curr_order_size = 10
        holdntrade.log = mock_logging
        holdntrade.conf = self.create_default_conf()

        holdntrade.create_sell_order(holdntrade.conf.change)

        assert not mock_create_limit_sell_order.called, 'create_order was called but should have not'

    @patch('holdntrade.logging')
    @mock.patch.object(ccxt.bitmex, 'create_limit_sell_order')
    def test_create_sell_order_should_create_order(self, mock_create_limit_sell_order, mock_logging):
        holdntrade.sell_price = 4000
        holdntrade.curr_sell = []
        holdntrade.curr_order_size = 10
        holdntrade.log = mock_logging
        holdntrade.conf = self.create_default_conf()
        holdntrade.exchange = ccxt.bitmex

        holdntrade.create_sell_order()

        mock_create_limit_sell_order.assert_called_with(holdntrade.conf.pair, holdntrade.curr_order_size,
                                                        holdntrade.sell_price)

    @patch('holdntrade.logging')
    @mock.patch.object(ccxt.bitmex, 'fetch_ticker')
    @mock.patch.object(ccxt.bitmex, 'create_limit_buy_order')
    def test_create_buy_order_should_not_create_order_if_order_is_below_limit(self, mock_create_limit_buy_order,
                                                                              mock_fetch_ticker, mock_logging):
        price = 8000
        holdntrade.curr_sell = []
        amount = 10
        holdntrade.log = mock_logging
        holdntrade.conf = self.create_default_conf()
        holdntrade.exchange = ccxt.bitmex
        mock_fetch_ticker.return_value = {'bid': 99}

        holdntrade.create_buy_order(price, amount)

        assert not mock_create_limit_buy_order.called, 'create_order was called but should have not'

    @patch('holdntrade.logging')
    @mock.patch.object(ccxt.bitmex, 'fetch_ticker')
    @mock.patch.object(ccxt.bitmex, 'create_limit_buy_order')
    def test_create_buy_order_should_create_order_if_order_is_above_limit(self, mock_create_limit_buy_order,
                                                                          mock_fetch_ticker, mock_logging):
        price = 4000
        holdntrade.curr_sell = []
        amount = 10
        holdntrade.log = mock_logging
        holdntrade.conf = self.create_default_conf()
        holdntrade.long_price = 1234
        holdntrade.exchange = ccxt.bitmex
        mock_fetch_ticker.return_value = {'bid': 99}

        holdntrade.create_buy_order(price, amount)

        mock_create_limit_buy_order.assert_called_with(holdntrade.conf.pair, amount, holdntrade.long_price)

    @staticmethod
    def create_default_conf():
        conf = holdntrade.ExchangeConfig
        conf.exchange = 'bitmex'
        conf.pair = 'FOOBAR/SNAFU'
        conf.change = 0.005
        conf.order_btc_min = 0.0025
        return conf


if __name__ == '__main__':
    unittest.main()
