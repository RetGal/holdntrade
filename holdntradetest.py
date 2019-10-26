import os
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
    @mock.patch.object(holdntrade, 'get_balance')
    def test_create_sell_order_should_not_create_order_if_order_is_below_limit(self, mock_get_balance,
                                                                               mock_create_limit_sell_order,
                                                                               mock_logging):
        holdntrade.SELL_PRICE = 8000
        holdntrade.SELL_ORDERS = []
        holdntrade.CURR_BUY_ORDER_SIZE = 10
        holdntrade.LOG = mock_logging
        holdntrade.CONF = self.create_default_conf()

        mock_get_balance.return_value = {'free': 20}

        holdntrade.create_sell_order(10)

        assert not mock_create_limit_sell_order.called, 'create_order was called but should have not'

    @patch('holdntrade.logging')
    @mock.patch.object(ccxt.bitmex, 'create_limit_sell_order')
    @mock.patch.object(holdntrade, 'get_balance')
    def test_create_sell_order_should_not_create_order_if_order_is_bigger_than_used_balance(self, mock_get_balance,
                                                                                            mock_create_limit_sell_order,
                                                                                            mock_logging):
        holdntrade.SELL_PRICE = 4000
        holdntrade.SELL_ORDERS = []
        holdntrade.CURR_BUY_ORDER_SIZE = 10
        holdntrade.LOG = mock_logging
        holdntrade.CONF = self.create_default_conf()

        mock_get_balance.return_value = {'free': 1}

        holdntrade.create_sell_order(40001)

        assert not mock_create_limit_sell_order.called, 'create_order was called but should have not'

    @patch('holdntrade.logging')
    @mock.patch.object(ccxt.bitmex, 'create_limit_sell_order')
    @mock.patch.object(holdntrade, 'get_balance')
    def test_create_sell_order_should_create_order(self, mock_get_balance, mock_create_limit_sell_order,
                                                   mock_logging):
        holdntrade.SELL_PRICE = 4000
        holdntrade.SELL_ORDERS = []
        holdntrade.CURR_BUY_ORDER_SIZE = 10
        holdntrade.LOG = mock_logging
        holdntrade.CONF = self.create_default_conf()

        mock_get_balance.return_value = {'free': 20}

        holdntrade.create_sell_order()

        mock_create_limit_sell_order.assert_called_with(holdntrade.CONF.pair, holdntrade.CURR_BUY_ORDER_SIZE,
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

        holdntrade.create_buy_order(price, amount)

        assert not mock_create_limit_buy_order.called, 'create_order was called but should have not'

    @patch('holdntrade.logging')
    @mock.patch.object(ccxt.bitmex, 'fetch_ticker')
    @mock.patch.object(ccxt.bitmex, 'create_limit_buy_order')
    def test_create_buy_order_should_create_order_if_order_is_above_limit(self, mock_create_limit_buy_order,
                                                                          mock_fetch_ticker, mock_logging):
        price = 4000
        holdntrade.SELL_ORDERS = []
        amount = 10
        holdntrade.LOG = mock_logging
        holdntrade.CONF = self.create_default_conf()
        holdntrade.BUY_PRICE = 1234
        holdntrade.EXCHANGE = ccxt.bitmex
        mock_fetch_ticker.return_value = {'bid': 99}

        holdntrade.create_buy_order(price, amount)

        mock_create_limit_buy_order.assert_called_with(holdntrade.CONF.pair, amount, holdntrade.BUY_PRICE)

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

    @patch('holdntrade.logging')
    def test_calculate_all_sold_balance(self, mock_logging):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.LOG = mock_logging
        holdntrade.EXCHANGE = holdntrade.connect_to_exchange()
        poi = {'homeNotional': 0.464}
        orders = [holdntrade.Order({'side': 'sell', 'id': '1', 'price': 40000, 'amount': 4444, 'datetime': datetime.datetime.today().isoformat()})]
        wallet_balance = 0.1995
        margin_balance = 0.1166
        net_deposits = 0.2

        all_sold_balance = holdntrade.calculate_all_sold_balance(poi, orders, wallet_balance, margin_balance, net_deposits)

        self.assertAlmostEqual(0.47, all_sold_balance, 2)

    def test_shall_hibernate_by_mm(self):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.CONF.mm_stop_buy = 2.3
        mayer = {'current': 2.4}

        self.assertTrue(holdntrade.shall_hibernate(mayer))

    @patch('holdntrade.get_leverage', return_value=1.1)
    @patch('holdntrade.get_target_leverage', return_value=1)
    def test_shall_hibernate_by_leverage(self, mock_get_target_leverage, mock_get_leverage):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.CONF.mm_stop_buy = 2.3
        holdntrade.CONF.auto_leverage_escape = False
        mayer = {'current': 1.4}

        self.assertTrue(holdntrade.shall_hibernate(mayer))

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

        result = holdntrade.load_existing_orders(holdntrade.OpenOrdersSummary(orders))

        self.assertTrue(result)
        self.assertEqual(10000, holdntrade.SELL_PRICE)
        self.assertEqual(8100, holdntrade.BUY_PRICE)

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

        avg_total = holdntrade.calculate_avg_entry_price_and_total_quantity(holdntrade.OpenOrdersSummary(orders).orders)

        self.assertEqual(8750, avg_total['avg'])
        self.assertEqual(40, avg_total['qty'])

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
    def test_get_target_leverage_for_mm_ceil(self, mock_logging):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.LOG = mock_logging

        target_leverage = holdntrade.get_target_leverage({'current': holdntrade.CONF.mm_ceil + 0.1})
        self.assertEqual(holdntrade.CONF.leverage_low, target_leverage)

    @patch('holdntrade.logging')
    def test_get_target_leverage_for_mm_floor(self, mock_logging):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.LOG = mock_logging

        target_leverage = holdntrade.get_target_leverage({'current': holdntrade.CONF.mm_floor - 0.1})
        self.assertEqual(holdntrade.CONF.leverage_high, target_leverage)

    @patch('holdntrade.logging')
    def test_get_target_leverage_default(self, mock_logging):
        holdntrade.CONF = self.create_default_conf()
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
    @patch('holdntrade.sleep_for', return_value=None)
    @patch('holdntrade.get_current_price', return_value=9000)
    @patch('holdntrade.calculate_buy_order_amount', return_value=99)
    @patch('holdntrade.shall_hibernate', return_value=False)
    @mock.patch.object(ccxt.bitmex, 'fetch_balance')
    @mock.patch.object(ccxt.bitmex, 'fetch_order_status')
    @mock.patch.object(ccxt.bitmex, 'create_limit_buy_order')
    def test_sell_executed(self, mock_create_limit_buy_order, mock_fetch_order_status, mock_fetch_balance,
                           mock_shall_hibernate, mock_calculate_buy_order_amount, mock_get_current_price,
                           mock_sleep_for, mock_logging):
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
        mock_create_limit_buy_order.assert_called_with(holdntrade.CONF.pair, 99, buy_price)

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
    @patch('holdntrade.set_initial_leverage')
    @patch('holdntrade.sleep_for', return_value=None)
    @patch('holdntrade.get_current_price', return_value=9000)
    @patch('holdntrade.calculate_buy_order_amount', return_value=100)
    @patch('holdntrade.shall_hibernate', return_value=False)
    @mock.patch.object(ccxt.bitmex, 'fetch_balance')
    @mock.patch.object(ccxt.bitmex, 'fetch_order_status')
    @mock.patch.object(ccxt.bitmex, 'create_limit_buy_order')
    @mock.patch.object(ccxt.bitmex, 'create_limit_sell_order')
    def test_buy_executed_regular(self, mock_create_limit_sell_order, mock_create_limit_buy_order,
                                  mock_fetch_order_status, mock_fetch_balance, mock_shall_hibernate,
                                  mock_calculate_buy_order_amount, mock_get_current_price, mock_sleep_for,
                                  mock_set_initial_leverage, mock_logging):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.CONF.base = 'BTC'
        holdntrade.LOG = mock_logging
        holdntrade.EXCHANGE = holdntrade.connect_to_exchange()
        holdntrade.INITIAL_LEVERAGE_SET = True
        holdntrade.CURR_BUY_ORDER = holdntrade.Order({'side': 'buy', 'id': '1B', 'price': 15000, 'amount': 222,
                                                      'datetime': datetime.datetime.today().isoformat()})
        holdntrade.BUY_ORDERS.append(holdntrade.CURR_BUY_ORDER)

        holdntrade.CURR_BUY_ORDER_SIZE = 222
        mock_fetch_balance.return_value = {'BTC': {'used': 300, 'free': 400, 'total': 700}}
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
    @mock.patch.object(ccxt.bitmex, 'create_limit_sell_order')
    def test_create_divided_sell_order(self, mock_create_limit_sell_order, mock_get_position_balance, mock_logging):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.CONF.base = 'BTC'
        holdntrade.LOG = mock_logging
        holdntrade.EXCHANGE = holdntrade.connect_to_exchange()
        mock_get_position_balance.return_value = 10000
        holdntrade.SELL_PRICE = 11110
        order = {'side': 'sell', 'id': '1s', 'price': holdntrade.SELL_PRICE,
                 'amount': round(10000 / holdntrade.CONF.quota),
                 'datetime': datetime.datetime.today().isoformat()}
        mock_create_limit_sell_order.return_value = order

        holdntrade.create_divided_sell_order()

        mock_logging.info.assert_called_with('Created %s', str(holdntrade.Order(order)))
        mock_create_limit_sell_order.assert_called_with(holdntrade.CONF.pair, round(10000 / holdntrade.CONF.quota),
                                                        holdntrade.SELL_PRICE)

    @patch('holdntrade.logging')
    @mock.patch.object(ccxt.bitmex, 'cancel_order')
    @mock.patch.object(ccxt.bitmex, 'fetch_balance')
    @mock.patch.object(ccxt.bitmex, 'fetch_ticker')
    @mock.patch.object(ccxt.bitmex, 'fetch_order_status')
    @mock.patch.object(ccxt.bitmex, 'create_limit_buy_order')
    @mock.patch.object(ccxt.bitmex, 'create_limit_sell_order')
    def test_spread_should_cancel_highest_buy_order_and_create_a_new_sell_and_buy_order(self,
                                                                                        mock_create_limit_sell_order,
                                                                                        mock_create_limit_buy_order,
                                                                                        mock_fetch_order_status,
                                                                                        mock_fetch_ticker,
                                                                                        mock_fetch_balance,
                                                                                        mock_cancel_order,
                                                                                        mock_logging):
        holdntrade.CONF = self.create_default_conf()
        holdntrade.CONF.base = 'BTC'
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
        holdntrade.LOG = mock_logging
        market_price = 300
        return_values = {'2': 'open'}
        mock_fetch_order_status.side_effect = return_values.get
        mock_fetch_ticker.return_value = {'bid': market_price}
        mock_fetch_balance.return_value = {'BTC': {'used': 300, 'free': 200, 'total': 500}}
        buy_price = round(market_price * (1 - holdntrade.CONF.change))
        sell_price = round(market_price * (1 + holdntrade.CONF.change))
        holdntrade.EXCHANGE = holdntrade.connect_to_exchange()

        holdntrade.spread(market_price)

        mock_fetch_order_status.assert_called_with(buy2.id)
        mock_cancel_order.assert_called_with(buy2.id)
        mock_create_limit_buy_order.assert_called_with('BTC/USD', 102, buy_price)
        mock_create_limit_sell_order.assert_called_with('BTC/USD', 102, sell_price)
        self.assertEqual(2, len(holdntrade.BUY_ORDERS))
        self.assertEqual(buy_price, holdntrade.BUY_PRICE)
        self.assertEqual(3, len(holdntrade.SELL_ORDERS))

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

    def test_config_parse(self):
        holdntrade.INSTANCE = 'test'
        conf = holdntrade.ExchangeConfig()

        self.assertEqual('BTC/USD', conf.pair)
        self.assertEqual('XBTUSD', conf.symbol)
        self.assertEqual('BTC', conf.base)
        self.assertEqual('USD', conf.quote)
        self.assertEqual(0.0025, conf.order_crypto_min)
        self.assertEqual(0.005, conf.change)
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

    @staticmethod
    def create_default_conf():
        conf = holdntrade.ExchangeConfig
        conf.exchange = 'bitmex'
        conf.pair = 'BTC/USD'
        conf.symbol = 'XBTUSD'
        conf.change = 0.005
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
        return conf


if __name__ == '__main__':
    unittest.main()
