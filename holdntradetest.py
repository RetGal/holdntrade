import holdntrade
import unittest
import time
import ccxt
from unittest import mock


class HoldntradeTest(unittest.TestCase):

    def test_connect_to_exchange_params_bitmex(self):
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

    def test_connect_to_exchange_params_kraken(self):
        conf = holdntrade.ExchangeConfig
        conf.exchange = 'kraken'
        conf.api_key = 'key'
        conf.api_secret = 'secret'
        conf.test = False

        exchange = holdntrade.connect_to_exchange(conf)

        self.assertEqual(exchange.id, conf.exchange)
        self.assertEqual(exchange.apiKey, conf.api_key)
        self.assertEqual(exchange.secret, conf.api_secret)

    def test_connect_to_exchange_params_liquid(self):
        conf = holdntrade.ExchangeConfig
        conf.exchange = 'liquid'
        conf.api_key = 'key'
        conf.api_secret = 'secret'
        conf.test = False

        exchange = holdntrade.connect_to_exchange(conf)

        self.assertEqual(exchange.id, conf.exchange)
        self.assertEqual(exchange.apiKey, conf.api_key)
        self.assertEqual(exchange.secret, conf.api_secret)

    def test_connect_to_exchange_should_fail_if_param_test_is_true_but_not_supported(self):
        conf = holdntrade.ExchangeConfig
        conf.exchange = 'kraken'
        conf.api_key = 'key'
        conf.api_secret = 'secret'
        conf.test = True

        with self.assertRaises(SystemExit) as context:
            holdntrade.connect_to_exchange(conf)

        self.assertTrue('test not supported' in str(context.exception))

    def test_connect_to_exchange_should_fail_if_exchange_not_supported(self):
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
        holdntrade.order_btc_min = 0.0025

        self.assertTrue(holdntrade.is_order_below_limit(amount, price))

    def test_is_order_below_limit_false(self):
        price = 4000
        amount = 10
        holdntrade.order_btc_min = 0.0025

        self.assertFalse(holdntrade.is_order_below_limit(amount, price))

    @mock.patch.object(ccxt.bitmex, 'create_order')
    def test_create_sell_order_should_not_create_order_if_order_is_below_limit(self, mock_create_order):
        holdntrade.sell_price = 8000
        holdntrade.curr_sell = []
        holdntrade.curr_order_size = 10
        change = 0.005
        holdntrade.order_btc_min = 0.0025

        holdntrade.create_sell_order(change)

        assert not mock_create_order.called, 'create_order was called but should have not'

    @mock.patch.object(ccxt.bitmex, 'create_order')
    def test_create_sell_order_should_create_order(self, mock_create_order):
        holdntrade.sell_price = 4000
        holdntrade.curr_sell = []
        holdntrade.curr_order_size = 10
        change = 0.005
        holdntrade.order_btc_min = 0.0025
        holdntrade.exchange = ccxt.bitmex

        holdntrade.create_sell_order(change)

        mock_create_order.assert_called_with(holdntrade.PAIR, 'limit', 'sell', holdntrade.curr_order_size, holdntrade.sell_price)

    @mock.patch.object(ccxt.bitmex, 'fetch_ticker')
    @mock.patch.object(ccxt.bitmex, 'create_order')
    def test_create_buy_order_should_not_create_order_if_order_is_below_limit(self, mock_create_order, mock_fetch_ticker):
        price = 8000
        holdntrade.curr_sell = []
        amount = 10
        change = 0.005
        holdntrade.order_btc_min = 0.0025
        holdntrade.exchange = ccxt.bitmex
        mock_fetch_ticker.return_value = {'bid': 99}

        holdntrade.create_buy_order(price, amount, change)

        assert not mock_create_order.called, 'create_order was called but should have not'

    @mock.patch.object(ccxt.bitmex, 'fetch_ticker')
    @mock.patch.object(ccxt.bitmex, 'create_order')
    def test_create_buy_order_should_create_order_if_order_is_above_limit(self, mock_create_order, mock_fetch_ticker):
        price = 4000
        holdntrade.curr_sell = []
        amount = 10
        change = 0.005
        holdntrade.long_price = 1234
        holdntrade.order_btc_min = 0.0025
        holdntrade.exchange = ccxt.bitmex
        mock_fetch_ticker.return_value = {'bid': 99}

        holdntrade.create_buy_order(price, amount, change)

        mock_create_order.assert_called_with(holdntrade.PAIR, 'limit', 'buy', amount, holdntrade.long_price)


if __name__ == '__main__':
    unittest.main()