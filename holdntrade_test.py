import os
import datetime
import math
import time
import unittest
from unittest import mock
from unittest.mock import patch, call
import ccxt
import holdntrade


class HoldntradeTest(unittest.TestCase):

    @patch('holdntrade.logging')
    def test_connect_to_exchange_params_bitmex(self, mock_logging):
        holdntrade.LOG = mock_logging
        conf = holdntrade.ExchangeConfig
        conf.exchange = 'bitmex'
        conf.api_key = 'key'
        conf.api_secret = 'secret'
        conf.test = True

        exchange = holdntrade.connect_to_exchange()

        self.assertEqual(conf.exchange, exchange.id)
        self.assertEqual(conf.api_key, exchange.apiKey)
        self.assertEqual(conf.api_secret, exchange.secret)
        self.assertEqual(exchange.urls['test'], exchange.urls['api'])

    @patch('holdntrade.logging')
    def test_connect_to_exchange_params_kraken(self, mock_logging):
        holdntrade.LOG = mock_logging
        conf = holdntrade.ExchangeConfig
        conf.exchange = 'kraken'
        conf.api_key = 'key'
        conf.api_secret = 'secret'
        conf.test = False

        exchange = holdntrade.connect_to_exchange()

        self.assertEqual(conf.exchange, exchange.id)
        self.assertEqual(conf.api_key, exchange.apiKey)
        self.assertEqual(conf.api_secret, exchange.secret)

    @patch('holdntrade.logging')
    def test_connect_to_exchange_params_liquid(self, mock_logging):
        holdntrade.LOG = mock_logging
        conf = holdntrade.ExchangeConfig
        conf.exchange = 'liquid'
        conf.api_key = 'key'
        conf.api_secret = 'secret'
        conf.test = False

        exchange = holdntrade.connect_to_exchange()

        self.assertEqual(conf.exchange, exchange.id)
        self.assertEqual(conf.api_key, exchange.apiKey)
        self.assertEqual(conf.api_secret, exchange.secret)

    @patch('holdntrade.logging')
    def test_connect_to_exchange_should_fail_if_param_test_is_true_but_not_supported(self, mock_logging):
        holdntrade.LOG = mock_logging
        conf = holdntrade.ExchangeConfig
        conf.exchange = 'kraken'
        conf.api_key = 'key'
        conf.api_secret = 'secret'
        conf.test = True

        with self.assertRaises(SystemExit) as context:
            holdntrade.connect_to_exchange()

        self.assertTrue('Test not supported' in str(context.exception))

    @patch('holdntrade.logging')
    def test_connect_to_exchange_should_fail_if_exchange_not_supported(self, mock_logging):
        holdntrade.LOG = mock_logging
        conf = holdntrade.ExchangeConfig
        conf.exchange = 'unknown'
        conf.api_key = 'key'
        conf.api_secret = 'secret'
        conf.test = False

        with self.assertRaises(Exception) as context:
            holdntrade.connect_to_exchange()

        self.assertTrue('unknown' in str(context.exception))

    def test_sleep_for(self):
        before = time.time()

        holdntrade.sleep_for(1, 3)

        after = time.time()
        diff = after - before
        self.assertGreater(diff, 1, 'Should have slept for more than 1 second, but did not')
        self.assertLessEqual(diff, 3, 'Should have slept for less than 3 seconds, but did not')

    def test_read_last_line(self):
        last_line = holdntrade.read_last_line('test.txt')
        self.assertEqual('mail_server = "mail.example.com"\n', last_line)

    def test_is_order_below_limit_true(self):
        price = 8000
        amount = 10
        holdntrade.CONF = self.create_default_conf()

        self.assertTrue(holdntrade.is_order_below_limit(amount, price))

    def test_is_order_negative_amount_below_limit_true(self):
        price = 8000
        amount = -10
        holdntrade.CONF = self.create_default_conf()

        self.assertTrue(holdntrade.is_order_below_limit(amount, price))

    def test_is_order_below_limit_false(self):
        price = 4000
        amount = 10
        holdntrade.CONF = self.create_default_conf()

        self.assertFalse(holdntrade.is_order_below_limit(amount, price))

    def test_is_order_negative_amount_below_limit_false(self):
        price = 4000
        amount = -10
        holdntrade.CONF = self.create_default_conf()

        self.assertFalse(holdntrade.is_order_below_limit(amount, price))

    @patch('holdntrade.logging')
    @mock.patch.object(ccxt.bitmex, 'fetch_balance')
    def test_get_balance(self, mock_fetch_balance, mock_logging):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.CONF.base = 'BTC'
        holdntrade.LOG = mock_logging
        holdntrade.EXCHANGE = holdntrade.connect_to_exchange()
        mock_fetch_balance.return_value = {'BTC': {'used': None, 'free': None, 'total': 100}}

        balance = holdntrade.get_balance()

        self.assertEqual(0, balance['used'])
        self.assertEqual(0, balance['free'])
        self.assertEqual(100, balance['total'])

    @patch('holdntrade.logging')
    @patch('holdntrade.get_balance', return_value={'free': 0.1})
    @patch('holdntrade.get_current_price', return_value=10000)
    def test_calculate_buy_order_size_should_return_expected_amount_for_first_buy(self, mock_get_current_price,
                                                                                  mock_get_balance, mock_logging):
        holdntrade.LOG = mock_logging
        holdntrade.CONF = self.create_default_conf()
        holdntrade.EXCHANGE = ccxt.bitmex

        buy_amount = holdntrade.calculate_buy_order_amount()

        self.assertEqual(0.1 * 10000 / holdntrade.CONF.quota, buy_amount)

    @patch('holdntrade.logging')
    @patch('holdntrade.get_position_balance', return_value=100)
    @patch('holdntrade.get_current_price', return_value=10000)
    @patch('holdntrade.create_sell_order')
    def test_create_first_sell_order_should_create_sell_order_with_expected_amount(self, mock_create_sell_order,
                                                                                   mock_get_current_price,
                                                                                   mock_get_position_balance,
                                                                                   mock_logging):
        holdntrade.LOG = mock_logging
        holdntrade.CONF = self.create_default_conf()
        holdntrade.EXCHANGE = ccxt.bitmex

        holdntrade.create_first_sell_order()

        assert mock_create_sell_order.called_with(10050, 25)

    @patch('holdntrade.logging')
    @mock.patch.object(ccxt.bitmex, 'create_limit_sell_order')
    @patch('holdntrade.get_position_balance', return_value=100)
    def test_create_sell_order_should_not_create_order_if_order_is_below_limit(self, mock_get_position_balance,
                                                                               mock_create_limit_sell_order,
                                                                               mock_logging):
        holdntrade.SELL_PRICE = 8000
        holdntrade.SELL_ORDERS = []
        holdntrade.CURR_BUY_ORDER_SIZE = 10
        holdntrade.LOG = mock_logging
        holdntrade.CONF = self.create_default_conf()

        holdntrade.create_sell_order(10)

        assert not mock_create_limit_sell_order.called, 'create_order was called but should have not'

    @patch('holdntrade.logging')
    @mock.patch.object(ccxt.bitmex, 'create_limit_sell_order')
    @patch('holdntrade.get_position_balance', return_value=1)
    def test_create_sell_order_should_not_create_order_if_order_is_bigger_than_used_balance(self,
                                                                                            mock_get_position_balance,
                                                                                            mock_create_limit_sell_order,
                                                                                            mock_logging):
        holdntrade.SELL_PRICE = 4000
        holdntrade.SELL_ORDERS = []
        holdntrade.CURR_BUY_ORDER_SIZE = 10
        holdntrade.LOG = mock_logging
        holdntrade.CONF = self.create_default_conf()

        holdntrade.create_sell_order(40001)

        assert not mock_create_limit_sell_order.called, 'create_order was called but should have not'

    @patch('holdntrade.logging')
    @mock.patch.object(ccxt.bitmex, 'create_limit_sell_order')
    @patch('holdntrade.get_position_balance', return_value=100)
    def test_create_sell_order_should_create_order(self, mock_get_position_balance, mock_create_limit_sell_order,
                                                   mock_logging):
        holdntrade.EXCHANGE = ccxt.bitmex
        holdntrade.SELL_PRICE = 4000
        holdntrade.SELL_ORDERS = []
        holdntrade.CURR_BUY_ORDER = holdntrade.Order({'id': 1, 'price': 3950, 'side': 'BUY', 'datetime': '', 'amount': 10})
        holdntrade.LOG = mock_logging
        holdntrade.CONF = self.create_default_conf()

        holdntrade.create_sell_order()

        mock_create_limit_sell_order.assert_called_with(holdntrade.CONF.pair, holdntrade.CURR_BUY_ORDER.amount,
                                                        holdntrade.SELL_PRICE)

    @patch('holdntrade.logging')
    @patch('holdntrade.fetch_mayer')
    @patch('holdntrade.adjust_leverage')
    @patch('holdntrade.shall_hibernate', return_value=False)
    @patch('holdntrade.get_balance', return_value={'free': 0.1})
    @patch('holdntrade.get_current_price', return_value=10000)
    @patch('holdntrade.create_buy_order')
    def test_create_first_buy_order_should_create_buy_order_with_expected_amount(self, mock_create_buy_order,
                                                                                 mock_get_current_price,
                                                                                 mock_get_balance,
                                                                                 mock_shall_hibernate,
                                                                                 mock_adjust_leverage,
                                                                                 mock_fetch_mayer, mock_logging):
        holdntrade.LOG = mock_logging
        holdntrade.CONF = self.create_default_conf()
        holdntrade.EXCHANGE = ccxt.bitmex
        holdntrade.FIRST_BUY = True

        holdntrade.create_first_buy_order()

        assert mock_create_buy_order.called_with(10000, 250)

    @patch('holdntrade.logging')
    @mock.patch.object(ccxt.bitmex, 'fetch_ticker')
    @mock.patch.object(ccxt.bitmex, 'create_limit_buy_order')
    def test_create_buy_order_should_not_create_order_if_order_is_below_limit(self, mock_create_limit_buy_order,
                                                                              mock_fetch_ticker, mock_logging):
        price = 8000
        holdntrade.SELL_ORDERS = []
        amount = 10
        holdntrade.LOG = mock_logging
        holdntrade.CONF = self.create_default_conf()
        holdntrade.EXCHANGE = ccxt.bitmex
        mock_fetch_ticker.return_value = {'bid': 99}

        holdntrade.create_buy_order(price, amount, False)

        assert not mock_create_limit_buy_order.called, 'create_order was called but should have not'

    @patch('holdntrade.logging')
    @mock.patch.object(ccxt.bitmex, 'fetch_ticker')
    @mock.patch.object(ccxt.bitmex, 'create_limit_buy_order')
    def test_create_buy_order_should_create_order_and_calculate_prices_if_order_is_above_limit(
            self, mock_create_limit_buy_order, mock_fetch_ticker, mock_logging):

        price = 4000
        holdntrade.SELL_ORDERS = []
        amount = 10
        holdntrade.LOG = mock_logging
        holdntrade.CONF = self.create_default_conf()
        holdntrade.EXCHANGE = ccxt.bitmex
        mock_fetch_ticker.return_value = {'bid': 99}
        expected_buy_price = 3980
        expected_sell_price = 4020

        holdntrade.create_buy_order(price, amount, False)

        self.assertEqual(expected_buy_price, holdntrade.BUY_PRICE)
        self.assertEqual(expected_sell_price, holdntrade.SELL_PRICE)
        mock_create_limit_buy_order.assert_called_with(holdntrade.CONF.pair, amount, expected_buy_price)

    @patch('holdntrade.logging')
    @mock.patch.object(ccxt.bitmex, 'fetch_ticker')
    @mock.patch.object(ccxt.bitmex, 'create_limit_buy_order')
    def test_create_buy_order_should_create_order_with_requested_price_if_order_is_above_limit(
            self, mock_create_limit_buy_order, mock_fetch_ticker, mock_logging):

        price = 4000
        holdntrade.SELL_ORDERS = []
        amount = 10
        holdntrade.LOG = mock_logging
        holdntrade.CONF = self.create_default_conf()
        holdntrade.EXCHANGE = ccxt.bitmex
        mock_fetch_ticker.return_value = {'bid': 99}
        expected_sell_price = 4020

        holdntrade.create_buy_order(price, amount, True)

        self.assertEqual(expected_sell_price, holdntrade.SELL_PRICE)
        mock_create_limit_buy_order.assert_called_with(holdntrade.CONF.pair, amount, price)

    @patch('holdntrade.logging')
    @mock.patch.object(ccxt.bitmex, 'fetch_order_status')
    def test_cancel_current_buy_order_should_remove_order_from_buy_orders_and_clear_current_buy_order(self,
                                                                                                      mock_fetch_order_status,
                                                                                                      mock_logging):
        new_order = {'id': '3f463352-8339-cfbb-3bde-45a63ba43e6c', 'price': 99, 'amount': 20, 'side': 'buy',
                     'datetime': datetime.datetime.now()}
        order = holdntrade.Order(new_order)
        holdntrade.BUY_ORDERS = [order]
        holdntrade.CURR_BUY_ORDER = order
        holdntrade.LOG = mock_logging
        holdntrade.CONF = self.create_default_conf()
        holdntrade.EXCHANGE = ccxt.bitmex
        mock_fetch_order_status(order.id).return_value = 'open'

        holdntrade.cancel_current_buy_order()

        self.assertFalse(holdntrade.CURR_BUY_ORDER)
        self.assertFalse(holdntrade.BUY_ORDERS)
        self.assertEqual(0, len(holdntrade.BUY_ORDERS))

    def test_stats_add_same_again_day(self):
        today = {'mBal': 0.999, 'price': 10000}
        stats = holdntrade.Stats(int(datetime.date.today().strftime("%Y%j")), today)
        same_day = {'mBal': 0.666, 'price': 9000}

        stats.add_day(int(datetime.date.today().strftime("%Y%j")), same_day)

        day = stats.get_day(int(datetime.date.today().strftime("%Y%j")))
        self.assertTrue(day['mBal'] == 0.999)
        self.assertTrue(day['price'] == 10000)

    def test_stats_add_day_removes_oldest(self):
        h72 = {'mBal': 0.720, 'price': 10072}
        h48 = {'mBal': 0.480, 'price': 10048}
        h24 = {'mBal': 0.240, 'price': 10024}
        today = {'mBal': 0.000, 'price': 10000}
        stats = holdntrade.Stats(int(datetime.date.today().strftime("%Y%j")) - 3, h72)
        stats.add_day(int(datetime.date.today().strftime("%Y%j")) - 2, h48)
        stats.add_day(int(datetime.date.today().strftime("%Y%j")) - 1, h24)
        self.assertTrue(len(stats.days) == 3)

        stats.add_day(int(datetime.date.today().strftime("%Y%j")), today)

        self.assertEqual(3, len(stats.days))
        self.assertTrue(stats.get_day(int(datetime.date.today().strftime("%Y%j")) - 3) is None)
        self.assertTrue(stats.get_day(int(datetime.date.today().strftime("%Y%j")) - 2) is not None)
        self.assertTrue(stats.get_day(int(datetime.date.today().strftime("%Y%j")) - 1) is not None)
        self.assertTrue(stats.get_day(int(datetime.date.today().strftime("%Y%j"))) is not None)

    def test_calculate_statistics_first_day(self):
        holdntrade.CONF = self.create_default_conf()

        today = holdntrade.calculate_daily_statistics(100, 8000.0)

        self.assertTrue(today['mBal'] == 100)
        self.assertTrue(today['price'] == 8000.0)

    def test_calculate_statistics_positive_change(self):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.STATS = holdntrade.Stats(int(datetime.date.today().strftime("%Y%j")) - 2,
                                            {'mBal': 75.15, 'price': 4400.0})
        holdntrade.STATS.add_day(int(datetime.date.today().strftime("%Y%j")) - 1, {'mBal': 50.1, 'price': 8000.0})

        today = holdntrade.calculate_daily_statistics(100.2, 8800.0)

        self.assertEqual(100.2, today['mBal'])
        self.assertEqual(8800.0, today['price'])
        self.assertEqual(100.0, today['mBalChan24'])
        self.assertEqual(10.0, today['priceChan24'])
        self.assertEqual(33.33, today['mBalChan48'])
        self.assertEqual(100.0, today['priceChan48'])

    def test_calculate_statistics_negative_change(self):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.STATS = holdntrade.Stats(int(datetime.date.today().strftime("%Y%j")) - 1,
                                            {'mBal': 150.3, 'price': 8000.0})

        today = holdntrade.calculate_daily_statistics(100.2, 7600.0)

        self.assertEqual(100.2, today['mBal'])
        self.assertEqual(7600.0, today['price'])
        self.assertEqual(-33.33, today['mBalChan24'])
        self.assertEqual(-5.0, today['priceChan24'])

    def test_calculate_used_margin_percentage(self):
        balance = {'total': 100, 'free': 20}

        percentage = holdntrade.calculate_used_margin_percentage(balance)

        self.assertEqual(80, percentage)

    @patch('holdntrade.logging')
    @mock.patch.object(ccxt.bitmex, 'fetch_balance')
    def test_calculate_used_margin_percentage_with_fetch(self, mock_fetch_balance, mock_logging):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.CONF.base = 'BTC'
        holdntrade.LOG = mock_logging
        holdntrade.EXCHANGE = holdntrade.connect_to_exchange()

        mock_fetch_balance.return_value = {holdntrade.CONF.base: {'free': 20, 'total': 100}}

        percentage = holdntrade.calculate_used_margin_percentage()

        mock_fetch_balance.assert_called()
        self.assertTrue(percentage == 80)

    def test_shall_hibernate_by_mm(self):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.CONF.mm_stop_buy = 2.3
        mayer = {'current': 2.4}

        self.assertTrue(holdntrade.shall_hibernate(mayer))

    @patch('holdntrade.get_leverage', return_value=2.1)
    def test_shall_hibernate_by_leverage_without_auto_leverage(self, mock_get_leverage):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.CONF.mm_stop_buy = 2.3
        holdntrade.CONF.auto_leverage_escape = False
        mayer = {'current': 1.4}

        self.assertTrue(holdntrade.shall_hibernate(mayer))

    @patch('holdntrade.get_leverage', return_value=1.1)
    @patch('holdntrade.get_target_leverage', return_value=1)
    def test_shall_hibernate_by_leverage(self, mock_get_target_leverage, mock_get_leverage):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.CONF.auto_leverage = True
        holdntrade.CONF.mm_stop_buy = 2.3
        holdntrade.CONF.auto_leverage_escape = False
        mayer = {'current': 1.4}

        self.assertTrue(holdntrade.shall_hibernate(mayer))

    @patch('holdntrade.get_leverage', return_value=1.1001)
    @patch('holdntrade.get_target_leverage', return_value=1.1)
    def test_shall_not_hibernate_by_leverage_if_leverage_is_only_a_fraction_too_high(self, mock_get_target_leverage,
                                                                                     mock_get_leverage):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.CONF.mm_stop_buy = 2.3
        holdntrade.CONF.auto_leverage_escape = False
        mayer = {'current': 1.4}

        self.assertFalse(holdntrade.shall_hibernate(mayer))

    @patch('holdntrade.get_leverage', return_value=3.1)
    @patch('holdntrade.get_target_leverage', return_value=1)
    def test_shall_hibernate_by_leverage_with_auto_escape(self, mock_get_target_leverage, mock_get_leverage):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.CONF.mm_stop_buy = 2.3
        mayer = {'current': 1.4}

        self.assertTrue(holdntrade.shall_hibernate(mayer))

    @patch('holdntrade.get_relevant_leverage', return_value=1.1)
    @patch('holdntrade.get_target_leverage', return_value=1)
    def test_shall_not_hibernate_by_leverage_with_auto_escape(self, mock_get_target_leverage, mock_get_relevant_leverage):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.CONF.mm_stop_buy = 2.3
        mayer = {'current': 1.4}

        self.assertFalse(holdntrade.shall_hibernate(mayer))

    @patch('holdntrade.get_relevant_leverage', return_value=1)
    @patch('holdntrade.get_target_leverage', return_value=1)
    def test_shall_not_hibernate(self, mock_get_target_leverage, mock_get_relevant_leverage):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.CONF.mm_stop_buy = 2.3
        holdntrade.CONF.auto_leverage_escape = False
        mayer = {'current': 1.8}

        self.assertFalse(holdntrade.shall_hibernate(mayer))

    def test_open_orders_summary_should_calculate_total_and_sort_orders_by_price(self):
        holdntrade.CONF = self.create_default_conf()
        orders = [{'side': 'sell', 'id': '12345abcde', 'price': 10000, 'amount': 50,
                   'datetime': datetime.datetime.today().isoformat()},
                  {'side': 'sell', 'id': '12345abcdf', 'price': 10100, 'amount': 49,
                   'datetime': datetime.datetime.today().isoformat()},
                  {'side': 'buy', 'id': '12345abcdg', 'price': 8000, 'amount': 150,
                   'datetime': datetime.datetime.today().isoformat()},
                  {'side': 'buy', 'id': '12345abcdh', 'price': 8100, 'amount': 49,
                   'datetime': datetime.datetime.today().isoformat()}]

        open_orders_summary = holdntrade.OpenOrdersSummary(orders)

        self.assertEqual(99, open_orders_summary.total_sell_order_value)
        self.assertEqual(199, open_orders_summary.total_buy_order_value)
        self.assertEqual(2, len(open_orders_summary.sell_orders))
        self.assertEqual(2, len(open_orders_summary.buy_orders))
        self.assertEqual(10100, open_orders_summary.sell_orders[0].price)
        self.assertEqual(8100, open_orders_summary.buy_orders[0].price)

    def test_open_orders_summary_for_kraken_should_calculate_total_in_fiat_and_sort_orders_by_price(self):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.CONF.exchange = 'kraken'
        orders = [{'side': 'sell', 'id': '12345abcde', 'price': 10000, 'amount': 0.01,
                   'datetime': datetime.datetime.today().isoformat()},
                  {'side': 'sell', 'id': '12345abcdf', 'price': 10100, 'amount': 0.005,
                   'datetime': datetime.datetime.today().isoformat()},
                  {'side': 'buy', 'id': '12345abcdg', 'price': 8000, 'amount': 0.01,
                   'datetime': datetime.datetime.today().isoformat()},
                  {'side': 'buy', 'id': '12345abcdh', 'price': 8100, 'amount': 0.015,
                   'datetime': datetime.datetime.today().isoformat()}]

        open_orders_summary = holdntrade.OpenOrdersSummary(orders)

        self.assertEqual(150.5, open_orders_summary.total_sell_order_value)
        self.assertEqual(201.5, open_orders_summary.total_buy_order_value)
        self.assertEqual(2, len(open_orders_summary.sell_orders))
        self.assertEqual(2, len(open_orders_summary.buy_orders))
        self.assertEqual(10100, open_orders_summary.sell_orders[0].price)
        self.assertEqual(8100, open_orders_summary.buy_orders[0].price)

    @patch('holdntrade.logging')
    def test_load_open_orders(self, mock_logging):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.LOG = mock_logging
        orders = [{'side': 'sell', 'id': '12345abcde', 'price': 10000, 'amount': 50,
                   'datetime': datetime.datetime.today().isoformat()},
                  {'side': 'sell', 'id': '12345abcdf', 'price': 10100, 'amount': 49,
                   'datetime': datetime.datetime.today().isoformat()},
                  {'side': 'buy', 'id': '12345abcdg', 'price': 8000, 'amount': 150,
                   'datetime': datetime.datetime.today().isoformat()},
                  {'side': 'buy', 'id': '12345abcdh', 'price': 8100, 'amount': 49,
                   'datetime': datetime.datetime.today().isoformat()}]

        holdntrade.load_existing_orders(holdntrade.OpenOrdersSummary(orders))

        self.assertEqual(10000, holdntrade.SELL_PRICE)
        self.assertEqual(8100, holdntrade.BUY_PRICE)

    @patch('holdntrade.logging')
    @patch('holdntrade.adjust_leverage')
    @patch('holdntrade.create_first_buy_order')
    @patch('holdntrade.create_first_sell_order')
    def test_auto_configure_no_buy_orders(self, mock_create_first_sell_order, mock_create_first_buy_order,
                                          mock_adjust_leverage, mock_logging):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.LOG = mock_logging
        orders = [{'side': 'sell', 'id': '12345abcde', 'price': 10000, 'amount': 50,
                   'datetime': datetime.datetime.today().isoformat()},
                  {'side': 'sell', 'id': '12345abcdf', 'price': 10100, 'amount': 49,
                   'datetime': datetime.datetime.today().isoformat()}]

        holdntrade.auto_configure(holdntrade.OpenOrdersSummary(orders))

        self.assertEqual(10000, holdntrade.SELL_PRICE)
        mock_adjust_leverage.asser_called()
        mock_create_first_sell_order.assert_not_called()
        mock_create_first_buy_order.assert_called()

    @patch('holdntrade.logging')
    @patch('holdntrade.adjust_leverage')
    @patch('holdntrade.create_first_buy_order')
    @patch('holdntrade.create_first_sell_order')
    def test_auto_configure_no_sell_orders(self, mock_create_first_sell_order, mock_create_first_buy_order,
                                           mock_adjust_leverage, mock_logging):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.LOG = mock_logging
        orders = [{'side': 'buy', 'id': '12345abcdg', 'price': 8000, 'amount': 150,
                   'datetime': datetime.datetime.today().isoformat()},
                  {'side': 'buy', 'id': '12345abcdh', 'price': 8100, 'amount': 49,
                   'datetime': datetime.datetime.today().isoformat()}]

        holdntrade.auto_configure(holdntrade.OpenOrdersSummary(orders))

        self.assertEqual(8100, holdntrade.BUY_PRICE)
        mock_adjust_leverage.asser_called()
        mock_create_first_sell_order.assert_called()
        mock_create_first_buy_order.assert_not_called()

    @patch('holdntrade.logging')
    def test_calculate_avg_entry_price_and_total_quantity(self, mock_logging):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.LOG = mock_logging
        orders = [{'side': 'sell', 'id': '12345abcde', 'price': 10000, 'amount': 10,
                   'datetime': datetime.datetime.today().isoformat()},
                  {'side': 'sell', 'id': '12345abcdf', 'price': 15000, 'amount': 10,
                   'datetime': datetime.datetime.today().isoformat()},
                  {'side': 'buy', 'id': '12345abcdg', 'price': 5000, 'amount': 20,
                   'datetime': datetime.datetime.today().isoformat()}]

        order_stats = holdntrade.calculate_order_stats(holdntrade.OpenOrdersSummary(orders).get_orders())

        self.assertEqual(8750, order_stats['avg'])
        self.assertEqual(40, order_stats['qty'])
        self.assertAlmostEqual(0.00567, order_stats['val'], 5)

    @patch('holdntrade.logging')
    @mock.patch.object(ccxt.bitmex, 'cancel_order')
    @mock.patch.object(ccxt.bitmex, 'fetch_order_status')
    def test_cancel_orders(self, mock_fetch_order_status, mock_cancel_order, mock_logging):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.LOG = mock_logging
        holdntrade.EXCHANGE = holdntrade.connect_to_exchange()

        orders = [holdntrade.Order({'side': 'sell', 'id': '1s', 'price': 10000, 'amount': 10,
                                    'datetime': datetime.datetime.today().isoformat()}),
                  holdntrade.Order({'side': 'sell', 'id': '2s', 'price': 15000, 'amount': 10,
                                    'datetime': datetime.datetime.today().isoformat()})]

        return_values = {'1s': 'open', '2s': 'canceled'}
        mock_fetch_order_status.side_effect = return_values.get
        holdntrade.cancel_orders(orders)

        mock_logging.debug.assert_called()
        mock_logging.warning.assert_called_with('Cancel %s was in state %s', str(orders[1]), 'canceled')
        mock_cancel_order.assert_called()

    @patch('holdntrade.logging')
    @mock.patch.object(ccxt.bitmex, 'fetch_balance')
    def test_get_margin_balance(self, mock_fetch_balance, mock_logging):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.CONF.base = 'BTC'
        holdntrade.LOG = mock_logging
        holdntrade.EXCHANGE = holdntrade.connect_to_exchange()

        mock_fetch_balance.return_value = {holdntrade.CONF.base: {'free': 100, 'total': 150}}
        holdntrade.get_margin_balance()

        mock_fetch_balance.assert_called()

    @patch('holdntrade.logging')
    @patch('ccxt.bitmex')
    def test_get_interest_rate(self, mock_bitmex, mock_logging):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.LOG = mock_logging
        holdntrade.EXCHANGE = mock_bitmex
        mock_bitmex.public_get_funding.return_value = [{'fundingRateDaily': 0.0001}]
        rate = holdntrade.get_interest_rate()

        today = datetime.date.today().isoformat()

        mock_bitmex.public_get_funding.assert_called_with({'symbol': holdntrade.CONF.symbol, 'startTime': today,
                                                           'count': 1})
        self.assertEqual(-0.01, rate)

    @patch('holdntrade.logging')
    def test_get_target_leverage_no_auto_leverage(self, mock_logging):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.LOG = mock_logging

        target_leverage = holdntrade.get_target_leverage({'current': 2.8})
        self.assertEqual(holdntrade.CONF.leverage_default, target_leverage)

    @patch('holdntrade.logging')
    def test_get_target_leverage_for_mm_ceil(self, mock_logging):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.CONF.auto_leverage = True
        holdntrade.LOG = mock_logging

        target_leverage = holdntrade.get_target_leverage({'current': holdntrade.CONF.mm_ceil + 0.1})
        self.assertEqual(holdntrade.CONF.leverage_low, target_leverage)

    @patch('holdntrade.logging')
    def test_get_target_leverage_for_mm_floor(self, mock_logging):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.CONF.auto_leverage = True
        holdntrade.LOG = mock_logging

        target_leverage = holdntrade.get_target_leverage({'current': holdntrade.CONF.mm_floor - 0.1})
        self.assertEqual(holdntrade.CONF.leverage_high, target_leverage)

    @patch('holdntrade.logging')
    def test_get_target_leverage_default(self, mock_logging):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.CONF.auto_leverage = True
        holdntrade.LOG = mock_logging

        target_leverage = holdntrade.get_target_leverage({'current': holdntrade.CONF.mm_floor + 0.1})
        self.assertEqual(holdntrade.CONF.leverage_default, target_leverage)

    @patch('holdntrade.logging')
    @patch('holdntrade.set_leverage')
    @patch('holdntrade.get_leverage')
    @patch('holdntrade.get_target_leverage')
    def test_adjust_leverage_from_too_low(self, mock_get_target_leverage, mock_get_leverage, mock_set_leverage,
                                          mock_logging):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.CONF.auto_leverage = True
        holdntrade.LOG = mock_logging
        mock_get_target_leverage.return_value = holdntrade.CONF.leverage_high
        leverages = [1.2]
        mock_get_leverage.side_effect = leverages

        holdntrade.adjust_leverage({'current': holdntrade.CONF.mm_ceil})

        mock_set_leverage.assert_called_with(1.3)

    @patch('holdntrade.logging')
    @patch('holdntrade.set_leverage')
    @patch('holdntrade.get_leverage')
    @patch('holdntrade.get_target_leverage')
    def test_adjust_leverage_from_far_too_high(self, mock_get_target_leverage, mock_get_leverage,
                                               mock_set_leverage, mock_logging):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.CONF.auto_leverage = True
        holdntrade.LOG = mock_logging
        mock_get_target_leverage.return_value = holdntrade.CONF.leverage_low
        leverages = [10, 2, 1.7, 1.5]
        mock_get_leverage.side_effect = leverages

        holdntrade.adjust_leverage({'current': holdntrade.CONF.mm_floor})

        mock_set_leverage.assert_called_with(1.5)

    @patch('holdntrade.logging')
    @patch('holdntrade.set_leverage')
    @patch('holdntrade.get_leverage')
    @patch('holdntrade.get_target_leverage')
    def test_adjust_leverage_from_too_high(self, mock_get_target_leverage, mock_get_leverage,
                                           mock_set_leverage, mock_logging):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.CONF.auto_leverage = True
        holdntrade.LOG = mock_logging
        mock_get_target_leverage.return_value = holdntrade.CONF.leverage_low
        leverages = [2, 1.7, 1.5]
        mock_get_leverage.side_effect = leverages

        holdntrade.adjust_leverage({'current': holdntrade.CONF.mm_floor})

        mock_set_leverage.assert_called_with(1.5)

    @patch('holdntrade.logging')
    @patch('holdntrade.set_leverage')
    @patch('holdntrade.get_leverage')
    @patch('holdntrade.get_target_leverage')
    def test_adjust_leverage_from_slightly_too_high(self, mock_get_target_leverage, mock_get_leverage,
                                                    mock_set_leverage, mock_logging):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.CONF.auto_leverage = True
        holdntrade.LOG = mock_logging
        mock_get_target_leverage.return_value = holdntrade.CONF.leverage_high
        leverages = [2.6]
        mock_get_leverage.side_effect = leverages

        holdntrade.adjust_leverage({'current': holdntrade.CONF.mm_floor})

        mock_set_leverage.assert_called_with(2.5)

    @patch('holdntrade.logging')
    @patch('holdntrade.get_relevant_leverage')
    @patch('ccxt.bitmex')
    def test_set_initial_leverage_required(self, mock_bitmex, mock_get_relevant_leverage, mock_logging):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.CONF.leverage_low = 0.8
        holdntrade.LOG = mock_logging
        holdntrade.EXCHANGE = mock_bitmex
        mock_get_relevant_leverage.return_value = 0

        holdntrade.set_initial_leverage()
        self.assertTrue(holdntrade.INITIAL_LEVERAGE_SET)
        mock_bitmex.private_post_position_leverage.assert_called_with({'symbol': holdntrade.CONF.symbol,
                                                                       'leverage': holdntrade.CONF.leverage_default})

    @patch('holdntrade.logging')
    @patch('holdntrade.get_relevant_leverage')
    @patch('ccxt.bitmex')
    def test_set_initial_leverage_not_required(self, mock_bitmex, mock_get_relevant_leverage, mock_logging):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.CONF.leverage_low = 0.8
        holdntrade.LOG = mock_logging
        holdntrade.EXCHANGE = mock_bitmex
        mock_get_relevant_leverage.return_value = 0.8

        holdntrade.set_initial_leverage()
        self.assertTrue(holdntrade.INITIAL_LEVERAGE_SET)
        mock_bitmex.private_post_position_leverage.assert_not_called

    @patch('holdntrade.logging')
    @mock.patch.object(holdntrade, 'get_leverage')
    @mock.patch.object(holdntrade, 'set_leverage')
    def test_boost_leverage_too_high(self, mock_set_leverage, mock_get_leverage, mock_logging):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.LOG = mock_logging
        mock_get_leverage.return_value = 3.08

        holdntrade.boost_leverage()

        mock_set_leverage.assert_not_called()

    @patch('holdntrade.logging')
    @mock.patch.object(holdntrade, 'get_leverage')
    @mock.patch.object(holdntrade, 'set_leverage')
    def test_boost_leverage(self, mock_set_leverage, mock_get_leverage, mock_logging):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.LOG = mock_logging
        mock_get_leverage.return_value = 2.88

        holdntrade.boost_leverage()

        mock_set_leverage.assert_called_with(2.98)

    @patch('holdntrade.logging')
    @mock.patch.object(ccxt.bitmex, 'fetch_order_status')
    def test_sell_executed_still_open(self, mock_fetch_order_status, mock_logging):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.LOG = mock_logging
        holdntrade.EXCHANGE = holdntrade.connect_to_exchange()
        holdntrade.SELL_ORDERS = [holdntrade.Order({'side': 'sell', 'id': '1s', 'price': 10000, 'amount': 10,
                                                    'datetime': datetime.datetime.today().isoformat()}),
                                  holdntrade.Order({'side': 'sell', 'id': '2s', 'price': 15000, 'amount': 10,
                                                    'datetime': datetime.datetime.today().isoformat()})]

        return_values = {'1s': 'open', '2s': 'open'}
        mock_fetch_order_status.side_effect = return_values.get

        holdntrade.sell_executed()

        mock_logging.debug.assert_called_with('Sell still open')

    @patch('holdntrade.logging')
    @patch('holdntrade.set_leverage')
    @patch('holdntrade.sleep_for', return_value=None)
    @patch('holdntrade.get_current_price', return_value=9000)
    @patch('holdntrade.calculate_buy_order_amount', return_value=99)
    @patch('holdntrade.shall_hibernate', return_value=False)
    @mock.patch.object(ccxt.bitmex, 'fetch_balance')
    @mock.patch.object(ccxt.bitmex, 'fetch_order_status')
    @mock.patch.object(ccxt.bitmex, 'create_limit_buy_order')
    @mock.patch.object(ccxt.bitmex, 'create_limit_sell_order')
    def test_sell_executed(self, mock_create_limit_sell_order, mock_create_limit_buy_order, mock_fetch_order_status,
                           mock_fetch_balance,mock_shall_hibernate, mock_calculate_buy_order_amount,
                           mock_get_current_price, mock_sleep_for, mock_set_leverage, mock_logging):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.CONF.base = 'BTC'
        holdntrade.LOG = mock_logging
        holdntrade.EXCHANGE = holdntrade.connect_to_exchange()
        holdntrade.SELL_ORDERS = [holdntrade.Order({'side': 'sell', 'id': '1s', 'price': 10000, 'amount': 10,
                                                    'datetime': datetime.datetime.today().isoformat()}),
                                  holdntrade.Order({'side': 'sell', 'id': '2s', 'price': 15000, 'amount': 10,
                                                    'datetime': datetime.datetime.today().isoformat()})]

        mock_fetch_balance.return_value = {'BTC': {'used': 300, 'free': 300, 'total': 600}}
        return_values = {'1s': 'closed', '2s': 'open'}
        mock_fetch_order_status.side_effect = return_values.get
        price = 9000
        buy_price = round(price * (1 - holdntrade.CONF.change))

        holdntrade.sell_executed()

        mock_logging.info.assert_called()
        mock_create_limit_sell_order.assert_not_called()
        mock_create_limit_buy_order.assert_called_with(holdntrade.CONF.pair, 99, buy_price)

    @patch('holdntrade.logging')
    @patch('holdntrade.get_current_price', return_value=9000)
    @patch('holdntrade.calculate_buy_order_amount', return_value=99)
    @patch('holdntrade.shall_hibernate', return_value=False)
    @patch('holdntrade.fetch_mayer', return_value={'current': 1, 'average': 1})
    @patch('holdntrade.adjust_leverage')
    @patch('holdntrade.create_sell_order')
    @patch('holdntrade.create_buy_order')
    @patch('holdntrade.calculate_sell_order_amount', return_value=1)
    @patch('holdntrade.fetch_order_status', return_value='closed')
    @patch('holdntrade.cancel_current_buy_order')
    def test_last_sell_executed(self, mock_cancel_current_buy_order, mock_fetch_order_status,
                                mock_calculate_sell_order_amount, mock_create_buy_order, mock_create_sell_order,
                                mock_adjust_leverage, mock_fetch_mayer, mock_shall_hibernate,
                                mock_calculate_buy_order_amount, mock_get_current_price, mock_logging):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.CONF.base = 'BTC'
        holdntrade.LOG = mock_logging
        holdntrade.SELL_ORDERS = [holdntrade.Order({'side': 'sell', 'id': '1s', 'price': 10000, 'amount': 10,
                                                    'datetime': datetime.datetime.today().isoformat()})]
        holdntrade.sell_executed()

        mock_logging.info.assert_called()
        mock_create_sell_order.assert_called()
        mock_create_buy_order.assert_called()

    @patch('holdntrade.logging')
    @patch('holdntrade.create_sell_order')
    @patch('holdntrade.create_buy_order')
    @patch('holdntrade.fetch_order_status', return_value='closed')
    def test_last_sell_executed_close_on_stop(self, mock_fetch_order_status,mock_create_sell_order,
                                              mock_create_buy_order, mock_logging):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.CONF.base = 'BTC'
        holdntrade.CONF.stop_on_top = True
        holdntrade.CONF.close_on_stop = True
        holdntrade.LOG = mock_logging
        holdntrade.SELL_ORDERS = [holdntrade.Order({'side': 'sell', 'id': '1s', 'price': 10000, 'amount': 10,
                                                    'datetime': datetime.datetime.today().isoformat()})]

        holdntrade.sell_executed()

        mock_logging.info.assert_called()
        mock_create_sell_order.assert_not_called()
        mock_create_buy_order.assert_not_called()

    @patch('holdntrade.logging')
    @mock.patch.object(ccxt.bitmex, 'fetch_ticker')
    @mock.patch.object(ccxt.bitmex, 'create_market_sell_order')
    def test_market_sell_order_bitmex(self, mock_create_market_sell_order, mock_fetch_ticker, mock_logging):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.CONF.base = 'BTC'
        holdntrade.LOG = mock_logging
        holdntrade.EXCHANGE = holdntrade.connect_to_exchange()
        market_price = 9000
        mock_fetch_ticker.return_value = {'bid': market_price}

        holdntrade.create_market_sell_order(0.01)

        mock_create_market_sell_order.assert_called_with(holdntrade.CONF.pair, round(0.01 * market_price))
        mock_logging.info.assert_called()

    @patch('holdntrade.logging')
    @mock.patch.object(ccxt.bitmex, 'fetch_ticker')
    @mock.patch.object(ccxt.bitmex, 'fetch_balance')
    @mock.patch.object(ccxt.bitmex, 'create_market_buy_order')
    def test_market_buy_order_bitmex(self, mock_create_market_buy_order, mock_fetch_balance, mock_fetch_ticker,
                                     mock_logging):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.CONF.base = 'BTC'
        holdntrade.LOG = mock_logging
        holdntrade.EXCHANGE = holdntrade.connect_to_exchange()
        market_price = 9000
        mock_fetch_ticker.return_value = {'bid': market_price}
        mock_fetch_balance.return_value = {'BTC': {'used': 300, 'free': 300, 'total': 600}}
        mock_fetch_ticker.return_value = {'bid': market_price}

        holdntrade.create_market_buy_order(0.01)

        mock_create_market_buy_order.assert_called_with(holdntrade.CONF.pair, round(0.01 * market_price))
        mock_logging.info.assert_called()

    @patch('holdntrade.logging')
    @patch('holdntrade.set_leverage')
    @patch('holdntrade.set_initial_leverage')
    @patch('holdntrade.sleep_for', return_value=None)
    @patch('holdntrade.get_current_price', return_value=9000)
    @patch('holdntrade.calculate_buy_order_amount', return_value=100)
    @patch('holdntrade.shall_hibernate', return_value=False)
    @patch('holdntrade.get_position_balance', return_value=800)
    @mock.patch.object(ccxt.bitmex, 'fetch_order_status')
    @mock.patch.object(ccxt.bitmex, 'create_limit_buy_order')
    @mock.patch.object(ccxt.bitmex, 'create_limit_sell_order')
    def test_buy_executed_regular(self, mock_create_limit_sell_order, mock_create_limit_buy_order,
                                  mock_fetch_order_status, mock_position_balance, mock_shall_hibernate,
                                  mock_calculate_buy_order_amount, mock_get_current_price, mock_sleep_for,
                                  mock_set_initial_leverage, mock_set_leverage, mock_logging):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.CONF.base = 'BTC'
        holdntrade.LOG = mock_logging
        holdntrade.EXCHANGE = holdntrade.connect_to_exchange()
        holdntrade.INITIAL_LEVERAGE_SET = True
        holdntrade.CURR_BUY_ORDER = holdntrade.Order({'side': 'buy', 'id': '1B', 'price': 15000, 'amount': 222,
                                                      'datetime': datetime.datetime.today().isoformat()})
        holdntrade.BUY_ORDERS.append(holdntrade.CURR_BUY_ORDER)

        holdntrade.CURR_BUY_ORDER_SIZE = 222
        mock_fetch_order_status.return_value = 'closed'
        price = 9000
        buy_price = round(price * (1 - holdntrade.CONF.change))
        sell_price = round(price * (1 + holdntrade.CONF.change))

        holdntrade.buy_executed()

        mock_logging.debug.assert_called()
        mock_set_initial_leverage.assert_not_called()
        mock_create_limit_sell_order.assert_called_with(holdntrade.CONF.pair, 222, sell_price)
        mock_create_limit_buy_order.assert_called_with(holdntrade.CONF.pair, 100, buy_price)

    @patch('holdntrade.logging')
    @patch('holdntrade.get_position_balance')
    @patch('holdntrade.calculate_quota', return_value=8)
    def test_calculate_sell_order_amount(self, mock_calculate_quota, mock_get_position_balance, mock_logging):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.LOG = mock_logging
        mock_get_position_balance.return_value = 10000

        amount = holdntrade.calculate_sell_order_amount()
        self.assertEqual(2500, amount)
        self.assertEqual(math.floor(10000 / holdntrade.CONF.quota), amount)
        mock_calculate_quota.assert_not_called()

        holdntrade.CONF.quota = 6
        amount = holdntrade.calculate_sell_order_amount()
        self.assertEqual(1666, amount)
        self.assertEqual(math.floor(10000 / holdntrade.CONF.quota), amount)
        mock_calculate_quota.assert_not_called()

        holdntrade.CONF.auto_quota = True
        amount = holdntrade.calculate_sell_order_amount()
        self.assertEqual(1250, amount)
        mock_calculate_quota.assert_called()

    @patch('holdntrade.logging')
    @patch('holdntrade.get_position_balance', return_value=200)
    @mock.patch.object(ccxt.bitmex, 'cancel_order')
    @mock.patch.object(ccxt.bitmex, 'fetch_ticker')
    @mock.patch.object(ccxt.bitmex, 'fetch_order_status')
    @patch('holdntrade.create_buy_order')
    @mock.patch.object(ccxt.bitmex, 'create_limit_sell_order')
    def test_spread_should_cancel_highest_buy_order_and_create_a_new_sell_and_buy_order(self,
                                                                                        mock_create_limit_sell_order,
                                                                                        mock_create_limit_buy_order,
                                                                                        mock_fetch_order_status,
                                                                                        mock_fetch_ticker,
                                                                                        mock_cancel_order,
                                                                                        mock_get_position_balance,
                                                                                        mock_logging):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.CONF.base = 'BTC'
        holdntrade.EXCHANGE = ccxt.bitmex
        holdntrade.LOG = mock_logging
        buy1 = holdntrade.Order({'id': '1', 'price': 100, 'amount': 101, 'side': 'buy',
                                 'datetime': datetime.datetime.now()})
        buy2 = holdntrade.Order({'id': '2', 'price': 200, 'amount': 102, 'side': 'buy',
                                 'datetime': datetime.datetime.now()})
        holdntrade.BUY_ORDERS = [buy1, buy2]
        sell1 = holdntrade.Order({'id': '3', 'price': 400, 'amount': 103, 'side': 'sell',
                                  'datetime': datetime.datetime.now()})
        sell2 = holdntrade.Order({'id': '4', 'price': 500, 'amount': 104, 'side': 'sell',
                                  'datetime': datetime.datetime.now()})
        holdntrade.SELL_ORDERS = [sell1, sell2]
        buy3 = holdntrade.Order({'id': '3', 'price': 301.5, 'amount': 102, 'side': 'buy',
                                 'datetime': datetime.datetime.now()})
        holdntrade.CURR_BUY_ORDER = buy3
        market_price = 300
        holdntrade.SELL_PRICE = round(market_price * (1 + holdntrade.CONF.change))
        return_values = {'2': 'open'}
        mock_fetch_order_status.side_effect = return_values.get
        mock_fetch_ticker.return_value = {'bid': market_price}

        holdntrade.spread(market_price)

        mock_fetch_order_status.assert_called_with(buy2.id)
        mock_cancel_order.assert_called_with(buy2.id)
        mock_create_limit_sell_order.assert_called_with('BTC/USD', 102, holdntrade.SELL_PRICE)
        self.assertEqual(3, len(holdntrade.SELL_ORDERS))

    @patch('holdntrade.get_margin_balance')
    @patch('holdntrade.get_current_price')
    def test_calculate_quota(self, mock_get_current_price, mock_get_margin_balance):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.CONF.auto_quota = True

        holdntrade.CONF.change = 0.002
        balances = [{'total': -0.04}, {'total': 0.02}, {'total': 0.4}, {'total': 4}, {'total': 10}, {'total': 100}]
        mock_get_margin_balance.side_effect = balances

        quota = holdntrade.calculate_quota(10000)
        self.assertEqual(2, quota)

        quota = holdntrade.calculate_quota(10000)
        self.assertEqual(2, quota)

        quota = holdntrade.calculate_quota(10000)
        self.assertEqual(4, quota)

        quota = holdntrade.calculate_quota(10000)
        self.assertEqual(11, quota)

        quota = holdntrade.calculate_quota(10000)
        self.assertEqual(17, quota)

        quota = holdntrade.calculate_quota(10000)
        self.assertEqual(20, quota)

        holdntrade.CONF.change = 0.008
        balances = [{'total': 0.005}, {'total': 1}, {'total': 10}, {'total': 25}, {'total': 250}]
        mock_get_margin_balance.side_effect = balances

        quota = holdntrade.calculate_quota(4000)
        self.assertEqual(2, quota)

        quota = holdntrade.calculate_quota(4000)
        self.assertEqual(5, quota)

        quota = holdntrade.calculate_quota(4000)
        self.assertEqual(12, quota)

        quota = holdntrade.calculate_quota(4000)
        self.assertEqual(18, quota)

        quota = holdntrade.calculate_quota(4000)
        self.assertEqual(20, quota)

        mock_get_margin_balance.side_effect = [{'total': 0.5932}]
        quota = holdntrade.calculate_quota(9139)
        self.assertEqual(6, quota)

        holdntrade.CONF.change = 0.032
        balances = [{'total': 0.01}, {'total': 0.2}, {'total': 2}, {'total': 5}, {'total': 50}]
        mock_get_margin_balance.side_effect = balances
        mock_get_current_price.return_value = 20000

        quota = holdntrade.calculate_quota()
        self.assertEqual(7, quota)

        quota = holdntrade.calculate_quota()
        self.assertEqual(10, quota)

        quota = holdntrade.calculate_quota()
        self.assertEqual(17, quota)

        quota = holdntrade.calculate_quota()
        self.assertEqual(20, quota)

        quota = holdntrade.calculate_quota()
        self.assertEqual(20, quota)

    @patch('holdntrade.logging')
    def test_calculate_all_sold_balance(self, mock_logging):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.LOG = mock_logging
        holdntrade.EXCHANGE = holdntrade.connect_to_exchange()
        poi = {'markPrice': 9160.34}
        orders = [holdntrade.Order({'side': 'sell', 'id': '1', 'price': 9441.5, 'amount': 262, 'datetime': datetime.datetime.today().isoformat()})]
        margin_balance = 0.1158

        all_sold_balance = holdntrade.calculate_all_sold_balance(poi, orders, margin_balance)

        self.assertAlmostEqual(0.1167, all_sold_balance, 4)

    @patch('holdntrade.logging')
    @mock.patch.object(os, 'remove')
    @mock.patch.object(holdntrade, 'send_mail')
    def test_deactivate_bot(self, mock_send_mail, mock_os_remove, mock_logging):
        holdntrade.INSTANCE = 'test'
        holdntrade.LOG = mock_logging

        terminated = False
        try:
            holdntrade.deactivate_bot()
        except SystemExit:
            terminated = True

        mock_os_remove.assert_called_with('test.pid')
        mock_send_mail.assert_called()
        self.assertTrue(terminated)

    @patch('holdntrade.logging')
    @patch('ccxt.bitmex.fetch_ticker', side_effect=ccxt.ExchangeError('key is disabled'))
    @mock.patch.object(holdntrade, 'deactivate_bot')
    def test_get_current_price_should_deactivate_bot(self, mock_deactivate_bot, mock_fetch_ticker, mock_logging):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.LOG = mock_logging
        holdntrade.EXCHANGE = holdntrade.connect_to_exchange()

        holdntrade.get_current_price()

        mock_deactivate_bot.assert_called()

    def test_keep_buying(self):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.CONF.stop_on_top = True
        holdntrade.CONF.change = 0.005

        sell1 = holdntrade.Order({'id': '3', 'price': 10050, 'amount': 1500, 'side': 'sell',
                                  'datetime': datetime.datetime.now()})
        sell2 = holdntrade.Order({'id': '4', 'price': 9950, 'amount': 1000, 'side': 'sell',
                                  'datetime': datetime.datetime.now()})
        holdntrade.SELL_ORDERS = [sell1, sell2]

        self.assertFalse(holdntrade.keep_buying(10000))

        self.assertTrue(holdntrade.keep_buying(9999))

        holdntrade.SELL_ORDERS = []
        self.assertFalse(holdntrade.keep_buying(9000))

        holdntrade.CONF.stop_on_top = False
        self.assertTrue(holdntrade.keep_buying(15000))

    @patch('holdntrade.get_balance')
    @patch('holdntrade.get_margin_balance')
    def test_compensate(self, mock_get_margin_balance, mock_get_balance):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.CONF.stop_on_top = True

        holdntrade.compensate()
        mock_get_balance.assert_not_called()
        mock_get_margin_balance.assert_not_called()

    @patch('holdntrade.logging')
    @patch('holdntrade.set_leverage')
    @patch('holdntrade.sleep_for', return_value=None)
    @patch('holdntrade.get_relevant_leverage')
    @patch('holdntrade.calculate_used_margin_percentage', return_value=77)
    def test_compact_position(self, mock_calculate_used_margin_percentage, mock_get_relevant_leverage, mock_sleep_for,
                              mock_set_leverage, mock_logging):
        holdntrade.LOG = mock_logging
        holdntrade.CONF = self.create_default_conf()

        mock_get_relevant_leverage.return_value = 3.321
        mock_set_leverage.side_effect = [True, True, True, True, False]
        first_call = call(3.3)
        last_call = call(2.9)

        holdntrade.compact_position()

        self.assertEqual(first_call, mock_set_leverage.mock_calls[0])
        self.assertEqual(last_call, mock_set_leverage.mock_calls[-1])

    @patch('holdntrade.set_leverage')
    @patch('holdntrade.calculate_used_margin_percentage', return_value=95)
    def test_compact_position_percentage_too_high(self, mock_calculate_used_margin_percentage, mock_set_leverage):
        holdntrade.compact_position()

        mock_set_leverage.assert_not_called()

    def test_config_parse(self):
        holdntrade.INSTANCE = 'test'
        conf = holdntrade.ExchangeConfig()

        self.assertEqual('test', conf.bot_instance)
        self.assertEqual('BTC/USD', conf.pair)
        self.assertEqual('XBTUSD', conf.symbol)
        self.assertEqual('BTC', conf.base)
        self.assertEqual('USD', conf.quote)
        self.assertEqual(0.0025, conf.order_crypto_min)
        self.assertEqual(0.005, conf.change)
        self.assertTrue(conf.auto_quota)
        self.assertEqual(5, conf.quota)
        self.assertEqual(30, conf.spread_factor)
        self.assertTrue(conf.auto_leverage)
        self.assertEqual(1.4, conf.leverage_default)
        self.assertEqual(0.8, conf.leverage_low)
        self.assertEqual(1.8, conf.leverage_high)
        self.assertEqual(1.0, conf.mm_floor)
        self.assertEqual(2.2, conf.mm_ceil)
        self.assertEqual(2.3, conf.mm_stop_buy)
        self.assertFalse(conf.auto_leverage_escape)
        self.assertEqual(4, conf.leverage_escape)
        self.assertEqual(5, conf.trade_trials)
        self.assertFalse(conf.stop_on_top)

    @staticmethod
    def create_default_conf():
        conf = holdntrade.ExchangeConfig
        conf.exchange = 'bitmex'
        conf.pair = 'BTC/USD'
        conf.symbol = 'XBTUSD'
        conf.change = 0.005
        conf.auto_quota = False
        conf.quota = 4
        conf.spread_factor = 2
        conf.order_crypto_min = 0.0025
        conf.bot_instance = 'test'
        conf.api_key = '1234'
        conf.api_secret = 'secret'
        conf.test = True
        conf.mm_ceil = 1.8
        conf.mm_floor = 0.9
        conf.mm_stop_buy = 2.3
        conf.auto_leverage = False
        conf.leverage_default = 2
        conf.leverage_high = 2.5
        conf.leverage_low = 1.5
        conf.leverage_escape = 3
        conf.auto_leverage_escape = True
        conf.trade_trials = 5
        conf.stop_on_top = False
        conf.close_on_stop = False
        return conf


if __name__ == '__main__':
    unittest.main()
