import datetime
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

        self.assertTrue('Test not supported' in str(context.exception))

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
    @mock.patch.object(holdntrade, 'get_used_balance')
    def test_create_sell_order_should_not_create_order_if_order_is_below_limit(self, mock_get_used_balance,
                                                                               mock_create_limit_sell_order,
                                                                               mock_logging):
        holdntrade.sell_price = 8000
        holdntrade.sell_orders = []
        holdntrade.curr_buy_order_size = 10
        holdntrade.log = mock_logging
        holdntrade.conf = self.create_default_conf()

        mock_get_used_balance.return_value = 20

        holdntrade.create_sell_order(holdntrade.conf.change)

        assert not mock_create_limit_sell_order.called, 'create_order was called but should have not'

    @patch('holdntrade.logging')
    @mock.patch.object(ccxt.bitmex, 'create_limit_sell_order')
    @mock.patch.object(holdntrade, 'get_used_balance')
    def test_create_sell_order_should_not_create_order_if_order_is_bigger_than_used_balance(self, mock_get_used_balance,
                                                                               mock_create_limit_sell_order,
                                                                               mock_logging):
        holdntrade.sell_price = 4000
        holdntrade.sell_orders = []
        holdntrade.curr_buy_order_size = 10
        holdntrade.log = mock_logging
        holdntrade.conf = self.create_default_conf()

        mock_get_used_balance.return_value = 9

        holdntrade.create_sell_order(holdntrade.conf.change)

        assert not mock_create_limit_sell_order.called, 'create_order was called but should have not'

    @patch('holdntrade.logging')
    @mock.patch.object(ccxt.bitmex, 'create_limit_sell_order')
    @mock.patch.object(holdntrade, 'get_used_balance')
    def test_create_sell_order_should_create_order(self, mock_get_used_balance, mock_create_limit_sell_order,
                                                   mock_logging):
        holdntrade.sell_price = 4000
        holdntrade.sell_orders = []
        holdntrade.curr_buy_order_size = 10
        holdntrade.log = mock_logging
        holdntrade.conf = self.create_default_conf()

        mock_get_used_balance.return_value = 20

        holdntrade.create_sell_order()

        mock_create_limit_sell_order.assert_called_with(holdntrade.conf.pair, holdntrade.curr_buy_order_size,
                                                        holdntrade.sell_price)

    @patch('holdntrade.logging')
    @mock.patch.object(ccxt.bitmex, 'fetch_ticker')
    @mock.patch.object(ccxt.bitmex, 'create_limit_buy_order')
    def test_create_buy_order_should_not_create_order_if_order_is_below_limit(self, mock_create_limit_buy_order,
                                                                              mock_fetch_ticker, mock_logging):
        price = 8000
        holdntrade.sell_orders = []
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
        holdntrade.sell_orders = []
        amount = 10
        holdntrade.log = mock_logging
        holdntrade.conf = self.create_default_conf()
        holdntrade.buy_price = 1234
        holdntrade.exchange = ccxt.bitmex
        mock_fetch_ticker.return_value = {'bid': 99}

        holdntrade.create_buy_order(price, amount)

        mock_create_limit_buy_order.assert_called_with(holdntrade.conf.pair, amount, holdntrade.buy_price)


    @patch('holdntrade.logging')
    @mock.patch.object(ccxt.bitmex, 'fetch_order_status')
    def test_cancel_current_buy_order_should_remove_order_from_buy_orders_and_clear_current_buy_order(self, mock_fetch_order_status, mock_logging):
        new_order = {'id': '3f463352-8339-cfbb-3bde-45a63ba43e6c', 'price': 99, 'amount': 20, 'side': 'buy',
                 'datetime': datetime.datetime.now()}
        order = holdntrade.Order(new_order)
        holdntrade.buy_orders = [order]
        holdntrade.curr_buy_order = order
        holdntrade.log = mock_logging
        holdntrade.conf = self.create_default_conf()
        holdntrade.exchange = ccxt.bitmex
        mock_fetch_order_status(order.id).return_value = 'open'

        holdntrade.cancel_current_buy_order()

        self.assertFalse(holdntrade.curr_buy_order)
        self.assertFalse(holdntrade.buy_orders)
        self.assertTrue(len(holdntrade.buy_orders) == 0)

    def test_calculate_statistics_first_day(self):
        holdntrade.conf = self.create_default_conf()

        days = holdntrade.calculate_statistics(100)

        self.assertTrue(len(days) == 3)
        today = days.pop(0)
        self.assertTrue(today['day'] == int(datetime.date.today().strftime("%j")))
        self.assertTrue(today['mBal'] == 100)

    def test_calculate_statistics_positive_change(self):
        holdntrade.conf = self.create_default_conf()
        holdntrade.stats = holdntrade.Stats(int(datetime.date.today().strftime("%j"))-1, {'mBal': 50.1})

        days = holdntrade.calculate_statistics(100.2)

        today = days.pop(0)
        self.assertTrue(today['day'] == int(datetime.date.today().strftime("%j")))
        self.assertTrue(today['mBal'] == 100.2)
        self.assertTrue(today['mChan'] == 100.0)

    def test_calculate_statistics_negative_change(self):
        holdntrade.conf = self.create_default_conf()
        holdntrade.stats = holdntrade.Stats(int(datetime.date.today().strftime("%j"))-1, {'mBal': 150.3})

        days = holdntrade.calculate_statistics(100.2)

        today = days.pop(0)
        self.assertTrue(today['day'] == int(datetime.date.today().strftime("%j")))
        self.assertTrue(today['mBal'] == 100.2)
        self.assertTrue(today['mChan'] == -33.33)

    # @patch('holdntrade.logging')
    # @mock.patch.object(ccxt.bitmex, 'cancel_order')
    # @mock.patch.object(ccxt.bitmex, 'fetch_order_status')
    # @mock.patch.object(ccxt.bitmex, 'create_limit_buy_order')
    # def test_spread(self, mock_create_limit_buy_order, mock_fetch_order_status, mock_cancel_order, mock_logging):
    #     holdntrade.conf = self.create_default_conf()
    #     buy1 = holdntrade.Order({'id': '1', 'price': 100, 'amount': 101, 'side': 'buy',
    #                              'datetime': datetime.datetime.now()})
    #     buy2 = holdntrade.Order({'id': '2', 'price': 200, 'amount': 102, 'side': 'buy',
    #                              'datetime': datetime.datetime.now()})
    #     holdntrade.buy_orders = [buy1, buy2]
    #     sell1 = holdntrade.Order({'id': '3', 'price': 400, 'amount': 103, 'side': 'sell',
    #                               'datetime': datetime.datetime.now()})
    #     sell2 = holdntrade.Order({'id': '4', 'price': 500, 'amount': 104, 'side': 'sell',
    #                               'datetime': datetime.datetime.now()})
    #     holdntrade.sell_orders = [sell1, sell2]
    #     market_price = 300
    #     holdntrade.log = mock_logging
    #     holdntrade.conf = self.create_default_conf()
    #     mock_fetch_order_status(buy2.id).return_value = 'open'
    #     buy_price = round(market_price * (1 - holdntrade.conf.change))
    #     mock_create_limit_buy_order(holdntrade.conf.pair, 102, buy_price).return_value = None
    #
    #     holdntrade.exchange = ccxt.bitmex({
    #         'apiKey': '123',
    #         'secret': '456',
    #     })
    #     holdntrade.exchange.urls['api'] = holdntrade.exchange.urls['test']
    #
    #     holdntrade.spread(market_price)
    #
    #     self.assertTrue(len(holdntrade.buy_orders) == 1)
    #
    #     mock_fetch_order_status.assert_called_with(buy2.id)
    #     mock_cancel_order.assert_called_with(buy2.id)


    @staticmethod
    def create_default_conf():
        conf = holdntrade.ExchangeConfig
        conf.exchange = 'bitmex'
        conf.pair = 'BTC/USD'
        conf.change = 0.005
        conf.divider = 4
        conf.spread_factor = 2
        conf.order_btc_min = 0.0025
        conf.bot_instance = 'test'
        return conf


if __name__ == '__main__':
    unittest.main()
