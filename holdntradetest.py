import unittest
from unittest import mock

import ccxt
import datetime
import time
from unittest.mock import patch

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

        exchange = holdntrade.connect_to_exchange()

        self.assertEqual(conf.exchange, exchange.id)
        self.assertEqual(conf.api_key, exchange.apiKey)
        self.assertEqual(conf.api_secret, exchange.secret)
        self.assertEqual(exchange.urls['test'], exchange.urls['api'])

    @patch('holdntrade.logging')
    def test_connect_to_exchange_params_kraken(self, mock_logging):
        holdntrade.log = mock_logging
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
        holdntrade.log = mock_logging
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
        holdntrade.log = mock_logging
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
        holdntrade.log = mock_logging
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
    @mock.patch.object(ccxt.bitmex, 'fetch_balance')
    def test_get_balance(self, mock_fetch_balance, mock_logging):
        holdntrade.conf = self.create_default_conf()
        holdntrade.conf.base = 'BTC'
        holdntrade.log = mock_logging
        holdntrade.exchange = holdntrade.connect_to_exchange()
        mock_fetch_balance.return_value = {'BTC': {'used': None, 'free': None, 'total': 100}}

        balance = holdntrade.get_balance()

        self.assertEqual(0, balance['used'])
        self.assertEqual(0, balance['free'])
        self.assertEqual(100, balance['total'])

    @patch('holdntrade.logging')
    @mock.patch.object(ccxt.bitmex, 'create_limit_sell_order')
    @mock.patch.object(holdntrade, 'get_balance')
    def test_create_sell_order_should_not_create_order_if_order_is_below_limit(self, mock_get_balance,
                                                                               mock_create_limit_sell_order,
                                                                               mock_logging):
        holdntrade.sell_price = 8000
        holdntrade.sell_orders = []
        holdntrade.curr_buy_order_size = 10
        holdntrade.log = mock_logging
        holdntrade.conf = self.create_default_conf()

        mock_get_balance.return_value = {'free': 20}

        holdntrade.create_sell_order(holdntrade.conf.change)

        assert not mock_create_limit_sell_order.called, 'create_order was called but should have not'

    @patch('holdntrade.logging')
    @mock.patch.object(ccxt.bitmex, 'create_limit_sell_order')
    @mock.patch.object(holdntrade, 'get_balance')
    def test_create_sell_order_should_not_create_order_if_order_is_bigger_than_used_balance(self, mock_get_balance,
                                                                                            mock_create_limit_sell_order,
                                                                                            mock_logging):
        holdntrade.sell_price = 4000
        holdntrade.sell_orders = []
        holdntrade.curr_buy_order_size = 10
        holdntrade.log = mock_logging
        holdntrade.conf = self.create_default_conf()

        mock_get_balance.return_value = {'free': 9}

        holdntrade.create_sell_order(holdntrade.conf.change)

        assert not mock_create_limit_sell_order.called, 'create_order was called but should have not'

    @patch('holdntrade.logging')
    @mock.patch.object(ccxt.bitmex, 'create_limit_sell_order')
    @mock.patch.object(holdntrade, 'get_balance')
    def test_create_sell_order_should_create_order(self, mock_get_balance, mock_create_limit_sell_order,
                                                   mock_logging):
        holdntrade.sell_price = 4000
        holdntrade.sell_orders = []
        holdntrade.curr_buy_order_size = 10
        holdntrade.log = mock_logging
        holdntrade.conf = self.create_default_conf()

        mock_get_balance.return_value = {'free': 20}

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
    def test_cancel_current_buy_order_should_remove_order_from_buy_orders_and_clear_current_buy_order(self,
                                                                                                      mock_fetch_order_status,
                                                                                                      mock_logging):
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
        self.assertEqual(0, len(holdntrade.buy_orders))

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
        holdntrade.conf = self.create_default_conf()

        today = holdntrade.calculate_daily_statistics(100, 8000.0)

        self.assertTrue(today['mBal'] == 100)
        self.assertTrue(today['price'] == 8000.0)

    def test_calculate_statistics_positive_change(self):
        holdntrade.conf = self.create_default_conf()
        holdntrade.stats = holdntrade.Stats(int(datetime.date.today().strftime("%Y%j")) - 2,
                                            {'mBal': 75.15, 'price': 4400.0})
        holdntrade.stats.add_day(int(datetime.date.today().strftime("%Y%j")) - 1, {'mBal': 50.1, 'price': 8000.0})

        today = holdntrade.calculate_daily_statistics(100.2, 8800.0)

        self.assertEqual(100.2, today['mBal'])
        self.assertEqual(8800.0, today['price'])
        self.assertEqual(100.0, today['mBalChan24'])
        self.assertEqual(10.0, today['priceChan24'])
        self.assertEqual(33.33, today['mBalChan48'])
        self.assertEqual(100.0, today['priceChan48'])

    def test_calculate_statistics_negative_change(self):
        holdntrade.conf = self.create_default_conf()
        holdntrade.stats = holdntrade.Stats(int(datetime.date.today().strftime("%Y%j")) - 1,
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
        holdntrade.conf = self.create_default_conf()
        holdntrade.conf.base = 'BTC'
        holdntrade.log = mock_logging
        holdntrade.exchange = holdntrade.connect_to_exchange()

        mock_fetch_balance.return_value = {holdntrade.conf.base: {'free': 20, 'total': 100}}

        percentage = holdntrade.calculate_used_margin_percentage()

        mock_fetch_balance.assert_called()
        self.assertTrue(percentage == 80)

    @patch('holdntrade.logging')
    def test_calculate_all_sold_balance(self, mock_logging):
        holdntrade.conf = self.create_default_conf()
        holdntrade.log = mock_logging
        holdntrade.exchange = holdntrade.connect_to_exchange()
        poi = {'homeNotional': 0.464}
        orders = [holdntrade.Order({'side': 'sell', 'id': '1', 'price': 40000, 'amount': 4444, 'datetime': datetime.datetime.today().isoformat()})]
        wallet_balance = 0.1995
        margin_balance = 0.1166
        net_deposits = 0.2

        all_sold_balance = holdntrade.calculate_all_sold_balance(poi, orders, wallet_balance, margin_balance, net_deposits)

        self.assertAlmostEqual(0.47, all_sold_balance, 2)

    def test_shall_hibernate_by_mm(self):
        holdntrade.conf = self.create_default_conf()
        holdntrade.conf.mm_stop_buy = 2.3
        mayer = {'current': 2.4}

        self.assertTrue(holdntrade.shall_hibernate(mayer))

    @patch('holdntrade.get_relevant_leverage', return_value=1.1)
    @patch('holdntrade.get_target_leverage', return_value=1)
    def test_shall_not_hibernate_by_leverage(self, mock_get_target_leverage, mock_get_relevant_leverage):
        holdntrade.conf = self.create_default_conf()
        holdntrade.conf.mm_stop_buy = 2.3
        mayer = {'current': 1.4}

        self.assertTrue(holdntrade.shall_hibernate(mayer))

    @patch('holdntrade.get_relevant_leverage', return_value=1)
    @patch('holdntrade.get_target_leverage', return_value=1)
    def test_shall_not_hibernate(self, mock_get_target_leverage, mock_get_relevant_leverage):
        holdntrade.conf = self.create_default_conf()
        holdntrade.conf.mm_stop_buy = 2.3
        mayer = {'current': 1.8}

        self.assertFalse(holdntrade.shall_hibernate(mayer))

    def test_open_orders_summary_should_calculate_total_and_sort_orders_by_price(self):
        holdntrade.conf = self.create_default_conf()
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
        holdntrade.conf = self.create_default_conf()
        holdntrade.conf.exchange = 'kraken'
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
        holdntrade.conf = self.create_default_conf()
        holdntrade.log = mock_logging
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
        self.assertEqual(10000, holdntrade.sell_price)
        self.assertEqual(8100, holdntrade.buy_price)

    @patch('holdntrade.logging')
    def test_calculate_avg_entry_price_and_total_quantity(self, mock_logging):
        holdntrade.conf = self.create_default_conf()
        holdntrade.log = mock_logging
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
        holdntrade.conf = self.create_default_conf()
        holdntrade.log = mock_logging
        holdntrade.exchange = holdntrade.connect_to_exchange()

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
        holdntrade.conf = self.create_default_conf()
        holdntrade.conf.base = 'BTC'
        holdntrade.log = mock_logging
        holdntrade.exchange = holdntrade.connect_to_exchange()

        mock_fetch_balance.return_value = {holdntrade.conf.base: {'free': 100, 'total': 150}}
        holdntrade.get_margin_balance()

        mock_fetch_balance.assert_called()

    @patch('holdntrade.logging')
    @patch('ccxt.bitmex')
    def test_get_interest_rate(self, mock_bitmex, mock_logging):
        holdntrade.conf = self.create_default_conf()
        holdntrade.log = mock_logging
        holdntrade.exchange = mock_bitmex
        mock_bitmex.public_get_funding.return_value = [{'fundingRateDaily': 0.0001}]
        rate = holdntrade.get_interest_rate()

        today = datetime.date.today().isoformat()

        mock_bitmex.public_get_funding.assert_called_with({'symbol': holdntrade.conf.symbol, 'startTime': today,
                                                           'count': 1})
        self.assertEqual(-0.01, rate)

    @patch('holdntrade.logging')
    def test_get_target_leverage_for_mm_ceil(self, mock_logging):
        holdntrade.conf = self.create_default_conf()
        holdntrade.log = mock_logging

        target_leverage = holdntrade.get_target_leverage({'current': holdntrade.conf.mm_ceil + 0.1})
        self.assertEqual(holdntrade.conf.leverage_low, target_leverage)

    @patch('holdntrade.logging')
    def test_get_target_leverage_for_mm_floor(self, mock_logging):
        holdntrade.conf = self.create_default_conf()
        holdntrade.log = mock_logging

        target_leverage = holdntrade.get_target_leverage({'current': holdntrade.conf.mm_floor - 0.1})
        self.assertEqual(holdntrade.conf.leverage_high, target_leverage)

    @patch('holdntrade.logging')
    def test_get_target_leverage_default(self, mock_logging):
        holdntrade.conf = self.create_default_conf()
        holdntrade.log = mock_logging

        target_leverage = holdntrade.get_target_leverage({'current': holdntrade.conf.mm_floor + 0.1})
        self.assertEqual(holdntrade.conf.leverage_default, target_leverage)

    @patch('holdntrade.logging')
    @patch('holdntrade.set_leverage')
    @patch('holdntrade.get_margin_leverage')
    @patch('holdntrade.get_target_leverage')
    def test_adjust_leverage_from_too_low(self, mock_get_target_leverage, mock_get_margin_leverage, mock_set_leverage,
                                          mock_logging):
        holdntrade.conf = self.create_default_conf()
        holdntrade.conf.auto_leverage = True
        holdntrade.log = mock_logging
        mock_get_target_leverage.return_value = holdntrade.conf.leverage_high
        leverages = [1.2]
        mock_get_margin_leverage.side_effect = leverages

        holdntrade.adjust_leverage({'current': holdntrade.conf.mm_ceil})

        mock_set_leverage.assert_called_with(1.3)

    @patch('holdntrade.logging')
    @patch('holdntrade.set_leverage')
    @patch('holdntrade.get_margin_leverage')
    @patch('holdntrade.get_target_leverage')
    def test_adjust_leverage_from_far_too_high(self, mock_get_target_leverage, mock_get_margin_leverage,
                                               mock_set_leverage, mock_logging):
        holdntrade.conf = self.create_default_conf()
        holdntrade.conf.auto_leverage = True
        holdntrade.log = mock_logging
        mock_get_target_leverage.return_value = holdntrade.conf.leverage_low
        leverages = [4, 3.7, 3.5]
        mock_get_margin_leverage.side_effect = leverages

        holdntrade.adjust_leverage({'current': holdntrade.conf.mm_floor})

        mock_set_leverage.assert_called_with(3.4)

    @patch('holdntrade.logging')
    @patch('holdntrade.set_leverage')
    @patch('holdntrade.get_margin_leverage')
    @patch('holdntrade.get_target_leverage')
    def test_adjust_leverage_from_slightly_too_high(self, mock_get_target_leverage, mock_get_margin_leverage,
                                                    mock_set_leverage, mock_logging):
        holdntrade.conf = self.create_default_conf()
        holdntrade.conf.auto_leverage = True
        holdntrade.log = mock_logging
        mock_get_target_leverage.return_value = holdntrade.conf.leverage_high
        leverages = [2.6]
        mock_get_margin_leverage.side_effect = leverages

        holdntrade.adjust_leverage({'current': holdntrade.conf.mm_floor})

        mock_set_leverage.assert_called_with(2.5)

    @patch('holdntrade.logging')
    @patch('holdntrade.get_relevant_leverage')
    @patch('ccxt.bitmex')
    def test_set_initial_leverage_required(self, mock_bitmex, mock_get_relevant_leverage, mock_logging):
        holdntrade.conf = self.create_default_conf()
        holdntrade.conf.leverage_low = 0.8
        holdntrade.log = mock_logging
        holdntrade.exchange = mock_bitmex
        mock_get_relevant_leverage.return_value = 0

        holdntrade.set_initial_leverage()
        self.assertTrue(holdntrade.initial_leverage_set)
        mock_bitmex.private_post_position_leverage.assert_called_with({'symbol': holdntrade.conf.symbol,
                                                                       'leverage': holdntrade.conf.leverage_default})

    @patch('holdntrade.logging')
    @patch('holdntrade.get_relevant_leverage')
    @patch('ccxt.bitmex')
    def test_set_initial_leverage_not_required(self, mock_bitmex, mock_get_relevant_leverage, mock_logging):
        holdntrade.conf = self.create_default_conf()
        holdntrade.conf.leverage_low = 0.8
        holdntrade.log = mock_logging
        holdntrade.exchange = mock_bitmex
        mock_get_relevant_leverage.return_value = 0.8

        holdntrade.set_initial_leverage()
        self.assertTrue(holdntrade.initial_leverage_set)
        mock_bitmex.private_post_position_leverage.assert_not_called

    @patch('holdntrade.logging')
    @mock.patch.object(holdntrade, 'get_margin_leverage')
    @mock.patch.object(holdntrade, 'set_leverage')
    def test_boost_leverage_too_high(self, mock_set_leverage, mock_get_margin_leverage, mock_logging):
        holdntrade.conf = self.create_default_conf()
        holdntrade.log = mock_logging
        mock_get_margin_leverage.return_value = 3.08

        holdntrade.boost_leverage()

        mock_set_leverage.assert_not_called()

    @patch('holdntrade.logging')
    @mock.patch.object(holdntrade, 'get_margin_leverage')
    @mock.patch.object(holdntrade, 'set_leverage')
    def test_boost_leverage(self, mock_set_leverage, mock_get_margin_leverage, mock_logging):
        holdntrade.conf = self.create_default_conf()
        holdntrade.log = mock_logging
        mock_get_margin_leverage.return_value = 2.88

        holdntrade.boost_leverage()

        mock_set_leverage.assert_called_with(2.98)

    @patch('holdntrade.logging')
    @mock.patch.object(ccxt.bitmex, 'fetch_order_status')
    def test_sell_executed_still_open(self, mock_fetch_order_status, mock_logging):
        holdntrade.conf = self.create_default_conf()
        holdntrade.log = mock_logging
        holdntrade.exchange = holdntrade.connect_to_exchange()
        holdntrade.sell_orders = [holdntrade.Order({'side': 'sell', 'id': '1s', 'price': 10000, 'amount': 10,
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
        holdntrade.conf = self.create_default_conf()
        holdntrade.conf.base = 'BTC'
        holdntrade.log = mock_logging
        holdntrade.exchange = holdntrade.connect_to_exchange()
        holdntrade.sell_orders = [holdntrade.Order({'side': 'sell', 'id': '1s', 'price': 10000, 'amount': 10,
                                                    'datetime': datetime.datetime.today().isoformat()}),
                                  holdntrade.Order({'side': 'sell', 'id': '2s', 'price': 15000, 'amount': 10,
                                                    'datetime': datetime.datetime.today().isoformat()})]

        mock_fetch_balance.return_value = {'BTC': {'used': 300, 'free': 300, 'total': 600}}
        return_values = {'1s': 'closed', '2s': 'open'}
        mock_fetch_order_status.side_effect = return_values.get
        price = 9000
        buy_price = round(price * (1 - holdntrade.conf.change))

        holdntrade.sell_executed()

        mock_logging.info.assert_called()
        mock_create_limit_buy_order.assert_called_with(holdntrade.conf.pair, 99, buy_price)

    @patch('holdntrade.logging')
    @mock.patch.object(ccxt.bitmex, 'fetch_ticker')
    @mock.patch.object(ccxt.bitmex, 'create_market_sell_order')
    def test_market_sell_order_bitmex(self, mock_create_market_sell_order, mock_fetch_ticker, mock_logging):
        holdntrade.conf = self.create_default_conf()
        holdntrade.conf.base = 'BTC'
        holdntrade.log = mock_logging
        holdntrade.exchange = holdntrade.connect_to_exchange()
        market_price = 9000
        mock_fetch_ticker.return_value = {'bid': market_price}

        holdntrade.create_market_sell_order(0.01)

        mock_create_market_sell_order.assert_called_with(holdntrade.conf.pair, round(0.01 * market_price))
        mock_logging.info.assert_called()

    @patch('holdntrade.logging')
    @mock.patch.object(ccxt.bitmex, 'fetch_ticker')
    @mock.patch.object(ccxt.bitmex, 'fetch_balance')
    @mock.patch.object(ccxt.bitmex, 'create_market_buy_order')
    def test_market_buy_order_bitmex(self, mock_create_market_buy_order, mock_fetch_balance, mock_fetch_ticker,
                                     mock_logging):
        holdntrade.conf = self.create_default_conf()
        holdntrade.conf.base = 'BTC'
        holdntrade.log = mock_logging
        holdntrade.exchange = holdntrade.connect_to_exchange()
        market_price = 9000
        mock_fetch_ticker.return_value = {'bid': market_price}
        mock_fetch_balance.return_value = {'BTC': {'used': 300, 'free': 300, 'total': 600}}
        mock_fetch_ticker.return_value = {'bid': market_price}

        holdntrade.create_market_buy_order(0.01)

        mock_create_market_buy_order.assert_called_with(holdntrade.conf.pair, round(0.01 * market_price))
        mock_logging.info.assert_called()

    @patch('holdntrade.logging')
    @patch('holdntrade.set_initial_leverage')
    @patch('holdntrade.sleep_for', return_value=None)
    @patch('holdntrade.get_current_price', return_value=9000)
    @patch('holdntrade.calculate_buy_order_amount', return_value=200)
    @patch('holdntrade.shall_hibernate', return_value=False)
    @mock.patch.object(ccxt.bitmex, 'fetch_balance')
    @mock.patch.object(ccxt.bitmex, 'create_limit_buy_order')
    @mock.patch.object(ccxt.bitmex, 'create_limit_sell_order')
    def test_buy_executed_first_run(self, mock_create_limit_sell_order, mock_create_limit_buy_order, mock_fetch_balance,
                                    mock_shall_hibernate, mock_calculate_buy_order_amount, mock_get_current_price,
                                    mock_sleep_for, mock_set_initial_leverage, mock_logging):
        holdntrade.conf = self.create_default_conf()
        holdntrade.conf.base = 'BTC'
        holdntrade.log = mock_logging
        holdntrade.exchange = holdntrade.connect_to_exchange()
        mock_fetch_balance.return_value = {'BTC': {'used': 300, 'free': 300, 'total': 600}}
        price = 9000
        buy_price = round(price * (1 - holdntrade.conf.change))
        sell_price = round(price * (1 + holdntrade.conf.change))

        holdntrade.buy_executed()

        mock_set_initial_leverage.assert_called()
        self.assertTrue(holdntrade.initial_leverage_set)
        mock_create_limit_sell_order.assert_called_with(holdntrade.conf.pair, 200, sell_price)
        mock_create_limit_buy_order.assert_called_with(holdntrade.conf.pair, 200, buy_price)

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
        holdntrade.conf = self.create_default_conf()
        holdntrade.conf.base = 'BTC'
        holdntrade.log = mock_logging
        holdntrade.exchange = holdntrade.connect_to_exchange()
        holdntrade.initial_leverage_set = True
        holdntrade.curr_buy_order = holdntrade.Order({'side': 'buy', 'id': '1B', 'price': 15000, 'amount': 222,
                                                      'datetime': datetime.datetime.today().isoformat()})
        holdntrade.buy_orders.append(holdntrade.curr_buy_order)

        holdntrade.curr_buy_order_size = 222
        mock_fetch_balance.return_value = {'BTC': {'used': 300, 'free': 400, 'total': 700}}
        mock_fetch_order_status.return_value = 'closed'
        price = 9000
        buy_price = round(price * (1 - holdntrade.conf.change))
        sell_price = round(price * (1 + holdntrade.conf.change))

        holdntrade.buy_executed()

        mock_logging.debug.assert_called()
        mock_set_initial_leverage.assert_not_called()
        mock_create_limit_sell_order.assert_called_with(holdntrade.conf.pair, 222, sell_price)
        mock_create_limit_buy_order.assert_called_with(holdntrade.conf.pair, 100, buy_price)

    @patch('holdntrade.logging')
    @patch('holdntrade.get_used_balance')
    @mock.patch.object(ccxt.bitmex, 'create_limit_sell_order')
    def test_create_divided_sell_order(self, mock_create_limit_sell_order, mock_get_used_balance, mock_logging):
        holdntrade.conf = self.create_default_conf()
        holdntrade.conf.base = 'BTC'
        holdntrade.log = mock_logging
        holdntrade.exchange = holdntrade.connect_to_exchange()
        mock_get_used_balance.return_value = 10000
        holdntrade.sell_price = 11110
        order = {'side': 'sell', 'id': '1s', 'price': holdntrade.sell_price,
                 'amount': round(10000 / holdntrade.conf.quota),
                 'datetime': datetime.datetime.today().isoformat()}
        mock_create_limit_sell_order.return_value = order

        holdntrade.create_divided_sell_order()

        mock_logging.info.assert_called_with('Created %s', str(holdntrade.Order(order)))
        mock_create_limit_sell_order.assert_called_with(holdntrade.conf.pair, round(10000 / holdntrade.conf.quota),
                                                        holdntrade.sell_price)

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
        holdntrade.conf = self.create_default_conf()
        holdntrade.conf.base = 'BTC'
        buy1 = holdntrade.Order({'id': '1', 'price': 100, 'amount': 101, 'side': 'buy',
                                 'datetime': datetime.datetime.now()})
        buy2 = holdntrade.Order({'id': '2', 'price': 200, 'amount': 102, 'side': 'buy',
                                 'datetime': datetime.datetime.now()})
        holdntrade.buy_orders = [buy1, buy2]
        sell1 = holdntrade.Order({'id': '3', 'price': 400, 'amount': 103, 'side': 'sell',
                                  'datetime': datetime.datetime.now()})
        sell2 = holdntrade.Order({'id': '4', 'price': 500, 'amount': 104, 'side': 'sell',
                                  'datetime': datetime.datetime.now()})
        holdntrade.sell_orders = [sell1, sell2]
        holdntrade.log = mock_logging
        market_price = 300
        return_values = {'2': 'open'}
        mock_fetch_order_status.side_effect = return_values.get
        mock_fetch_ticker.return_value = {'bid': market_price}
        mock_fetch_balance.return_value = {'BTC': {'used': 300, 'free': 200, 'total': 500}}
        buy_price = round(market_price * (1 - holdntrade.conf.change))
        sell_price = round(market_price * (1 + holdntrade.conf.change))
        holdntrade.exchange = holdntrade.connect_to_exchange()

        holdntrade.spread(market_price)

        mock_fetch_order_status.assert_called_with(buy2.id)
        mock_cancel_order.assert_called_with(buy2.id)
        mock_create_limit_buy_order.assert_called_with('BTC/USD', 102, buy_price)
        mock_create_limit_sell_order.assert_called_with('BTC/USD', 102, sell_price)
        self.assertEqual(2, len(holdntrade.buy_orders))
        self.assertEqual(buy_price, holdntrade.buy_price)
        self.assertEqual(3, len(holdntrade.sell_orders))

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
        return conf


if __name__ == '__main__':
    unittest.main()
