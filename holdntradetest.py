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
    @mock.patch.object(ccxt.bitmex, 'fetch_balance')
    def test_get_balance(self, mock_fetch_balance, mock_logging):
        holdntrade.conf = self.create_default_conf()
        holdntrade.conf.base = 'BTC'
        holdntrade.log = mock_logging
        holdntrade.exchange = holdntrade.connect_to_exchange(holdntrade.conf)
        mock_fetch_balance.return_value = {'BTC': {'used': None, 'free': None, 'total': 100}}

        balance = holdntrade.get_balance()

        self.assertTrue(balance['used'] == 0)
        self.assertTrue(balance['free'] == 0)
        self.assertTrue(balance['total'] == 100)

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
        self.assertTrue(len(holdntrade.buy_orders) == 0)

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

        self.assertTrue(len(stats.days) == 3)
        self.assertTrue(stats.get_day(int(datetime.date.today().strftime("%Y%j")) - 3) is None)
        self.assertTrue(stats.get_day(int(datetime.date.today().strftime("%Y%j")) - 2) is not None)
        self.assertTrue(stats.get_day(int(datetime.date.today().strftime("%Y%j")) - 1) is not None)
        self.assertTrue(stats.get_day(int(datetime.date.today().strftime("%Y%j"))) is not None)

    def test_calculate_statistics_first_day(self):
        holdntrade.conf = self.create_default_conf()

        today = holdntrade.calculate_daily_statistics(100, 8000.0)

        self.assertTrue(today['day'] == int(datetime.date.today().strftime("%Y%j")))
        self.assertTrue(today['mBal'] == 100)
        self.assertTrue(today['price'] == 8000.0)

    def test_calculate_statistics_positive_change(self):
        holdntrade.conf = self.create_default_conf()
        holdntrade.stats = holdntrade.Stats(int(datetime.date.today().strftime("%Y%j")) - 2,
                                            {'mBal': 75.15, 'price': 4400.0})
        holdntrade.stats.add_day(int(datetime.date.today().strftime("%Y%j")) - 1, {'mBal': 50.1, 'price': 8000.0})

        today = holdntrade.calculate_daily_statistics(100.2, 8800.0)

        self.assertTrue(today['day'] == int(datetime.date.today().strftime("%Y%j")))
        self.assertTrue(today['mBal'] == 100.2)
        self.assertTrue(today['price'] == 8800.0)
        self.assertTrue(today['mBalChan24'] == 100.0)
        self.assertTrue(today['priceChan24'] == 10.0)
        self.assertTrue(today['mBalChan48'] == 33.33)
        self.assertTrue(today['priceChan48'] == 100.0)

    def test_calculate_statistics_negative_change(self):
        holdntrade.conf = self.create_default_conf()
        holdntrade.stats = holdntrade.Stats(int(datetime.date.today().strftime("%Y%j")) - 1,
                                            {'mBal': 150.3, 'price': 8000.0})

        today = holdntrade.calculate_daily_statistics(100.2, 7600.0)

        self.assertTrue(today['day'] == int(datetime.date.today().strftime("%Y%j")))
        self.assertTrue(today['mBal'] == 100.2)
        self.assertTrue(today['price'] == 7600.0)
        self.assertTrue(today['mBalChan24'] == -33.33)
        self.assertTrue(today['priceChan24'] == -5.0)

    def test_calculate_used_margin_percentage(self):
        balance = {'total': 100, 'free': 20}

        percentage = holdntrade.calculate_used_margin_percentage(balance)

        self.assertTrue(percentage == 80)

    @patch('holdntrade.logging')
    @mock.patch.object(ccxt.bitmex, 'fetch_balance')
    def test_calculate_used_margin_percentage_with_fetch(self, mock_fetch_balance, mock_logging):
        holdntrade.conf = self.create_default_conf()
        holdntrade.conf.base = 'BTC'
        holdntrade.log = mock_logging
        holdntrade.exchange = holdntrade.connect_to_exchange(holdntrade.conf)

        mock_fetch_balance.return_value = {holdntrade.conf.base: {'free': 20, 'total': 100}}

        percentage = holdntrade.calculate_used_margin_percentage()

        mock_fetch_balance.assert_called()
        self.assertTrue(percentage == 80)

    def test_shall_hibernate(self):
        holdntrade.conf = self.create_default_conf()
        holdntrade.conf.mm_stop_buy = 2.3
        mayer = {'current': 2.4}

        self.assertTrue(holdntrade.shall_hibernate(mayer))

    def test_shall_not_hibernate(self):
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

        self.assertTrue(open_orders_summary.total_sell_order_value == 99)
        self.assertTrue(open_orders_summary.total_buy_order_value == 199)
        self.assertTrue(len(open_orders_summary.sell_orders) == 2)
        self.assertTrue(len(open_orders_summary.buy_orders) == 2)
        self.assertTrue(open_orders_summary.sell_orders[0].price == 10100)
        self.assertTrue(open_orders_summary.buy_orders[0].price == 8100)

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

        self.assertTrue(open_orders_summary.total_sell_order_value == 150.5)
        self.assertTrue(open_orders_summary.total_buy_order_value == 201.5)
        self.assertTrue(len(open_orders_summary.sell_orders) == 2)
        self.assertTrue(len(open_orders_summary.buy_orders) == 2)
        self.assertTrue(open_orders_summary.sell_orders[0].price == 10100)
        self.assertTrue(open_orders_summary.buy_orders[0].price == 8100)

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
        self.assertTrue(holdntrade.sell_price == 10000)
        self.assertTrue(holdntrade.buy_price == 8100)

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

        self.assertTrue(avg_total['avg'] == 8750)
        self.assertTrue(avg_total['qty'] == 40)

    @patch('holdntrade.logging')
    @mock.patch.object(ccxt.bitmex, 'cancel_order')
    @mock.patch.object(ccxt.bitmex, 'fetch_order_status')
    def test_cancel_orders(self, mock_fetch_order_status, mock_cancel_order, mock_logging):
        holdntrade.conf = self.create_default_conf()
        holdntrade.log = mock_logging
        holdntrade.exchange = holdntrade.connect_to_exchange(holdntrade.conf)

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
        holdntrade.exchange = holdntrade.connect_to_exchange(holdntrade.conf)

        mock_fetch_balance.return_value = {holdntrade.conf.base: {'free': 100, 'total': 150}}
        holdntrade.get_margin_balance()

        mock_fetch_balance.assert_called()

    @patch('holdntrade.logging')
    @mock.patch.object(ccxt.bitmex, 'fetch_order_status')
    def test_sell_executed_still_open(self, mock_fetch_order_status, mock_logging):
        holdntrade.conf = self.create_default_conf()
        holdntrade.log = mock_logging
        holdntrade.exchange = holdntrade.connect_to_exchange(holdntrade.conf)
        holdntrade.sell_orders = [holdntrade.Order({'side': 'sell', 'id': '1s', 'price': 10000, 'amount': 10,
                                                    'datetime': datetime.datetime.today().isoformat()}),
                                  holdntrade.Order({'side': 'sell', 'id': '2s', 'price': 15000, 'amount': 10,
                                                    'datetime': datetime.datetime.today().isoformat()})]

        return_values = {'1s': 'open', '2s': 'open'}
        mock_fetch_order_status.side_effect = return_values.get

        holdntrade.sell_executed(8888, 99)

        mock_logging.debug.assert_called_with('Sell still open')

    @patch('holdntrade.logging')
    @mock.patch.object(ccxt.bitmex, 'fetch_balance')
    @mock.patch.object(ccxt.bitmex, 'fetch_ticker')
    @mock.patch.object(ccxt.bitmex, 'fetch_order_status')
    @mock.patch.object(ccxt.bitmex, 'create_limit_buy_order')
    def test_sell_executed(self, mock_create_limit_buy_order, mock_fetch_order_status, mock_fetch_ticker,
                           mock_fetch_balance, mock_logging):
        holdntrade.conf = self.create_default_conf()
        holdntrade.log = mock_logging
        holdntrade.exchange = holdntrade.connect_to_exchange(holdntrade.conf)
        holdntrade.sell_orders = [holdntrade.Order({'side': 'sell', 'id': '1s', 'price': 10000, 'amount': 10,
                                                    'datetime': datetime.datetime.today().isoformat()}),
                                  holdntrade.Order({'side': 'sell', 'id': '2s', 'price': 15000, 'amount': 10,
                                                    'datetime': datetime.datetime.today().isoformat()})]

        mock_fetch_balance.return_value = {'BTC': {'used': 300, 'free': 300, 'total': 600}}
        return_values = {'1s': 'closed', '2s': 'open'}
        mock_fetch_order_status.side_effect = return_values.get
        market_price = 9000
        mock_fetch_ticker.return_value = {'bid': market_price}
        price = 8888
        buy_price = round(price * (1 - holdntrade.conf.change))

        holdntrade.sell_executed(price, 99)

        mock_logging.info.assert_called()
        mock_create_limit_buy_order.assert_called_with(holdntrade.conf.pair, 99, buy_price)

    @patch('holdntrade.logging')
    @mock.patch.object(ccxt.bitmex, 'fetch_ticker')
    @mock.patch.object(ccxt.bitmex, 'create_market_sell_order')
    def test_market_sell_order_bitmex(self, mock_create_market_sell_order, mock_fetch_ticker, mock_logging):
        holdntrade.conf = self.create_default_conf()
        holdntrade.conf.base = 'BTC'
        holdntrade.log = mock_logging
        holdntrade.exchange = holdntrade.connect_to_exchange(holdntrade.conf)
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
        holdntrade.exchange = holdntrade.connect_to_exchange(holdntrade.conf)
        market_price = 9000
        mock_fetch_ticker.return_value = {'bid': market_price}
        mock_fetch_balance.return_value = {'BTC': {'used': 300, 'free': 300, 'total': 600}}
        mock_fetch_ticker.return_value = {'bid': market_price}

        holdntrade.create_market_buy_order(0.01)

        mock_create_market_buy_order.assert_called_with(holdntrade.conf.pair, round(0.01 * market_price))
        mock_logging.info.assert_called()

    @patch('holdntrade.logging')
    @mock.patch.object(ccxt.bitmex, 'fetch_ticker')
    @mock.patch.object(ccxt.bitmex, 'fetch_balance')
    @mock.patch.object(ccxt.bitmex, 'create_limit_buy_order')
    @mock.patch.object(ccxt.bitmex, 'create_limit_sell_order')
    def test_buy_executed_first_run(self, mock_create_limit_sell_order, mock_create_limit_buy_order, mock_fetch_balance,
                                    mock_fetch_ticker, mock_logging):
        holdntrade.conf = self.create_default_conf()
        holdntrade.conf.base = 'BTC'
        holdntrade.log = mock_logging
        holdntrade.exchange = holdntrade.connect_to_exchange(holdntrade.conf)
        market_price = 9000
        mock_fetch_ticker.return_value = {'bid': market_price}
        mock_fetch_balance.return_value = {'BTC': {'used': 300, 'free': 300, 'total': 600}}
        price = 9999
        buy_price = round(price * (1 - holdntrade.conf.change))
        sell_price = round(price * (1 + holdntrade.conf.change))

        holdntrade.buy_executed(price, 200)

        mock_create_limit_sell_order.assert_called_with(holdntrade.conf.pair, 200, sell_price)
        mock_create_limit_buy_order.assert_called_with(holdntrade.conf.pair, 200, buy_price)

    @patch('holdntrade.logging')
    @mock.patch.object(ccxt.bitmex, 'fetch_ticker')
    @mock.patch.object(ccxt.bitmex, 'fetch_balance')
    @mock.patch.object(ccxt.bitmex, 'fetch_order_status')
    @mock.patch.object(ccxt.bitmex, 'create_limit_buy_order')
    @mock.patch.object(ccxt.bitmex, 'create_limit_sell_order')
    def test_buy_executed_regular(self, mock_create_limit_sell_order, mock_create_limit_buy_order,
                                  mock_fetch_order_status, mock_fetch_balance, mock_fetch_ticker, mock_logging):
        holdntrade.conf = self.create_default_conf()
        holdntrade.conf.base = 'BTC'
        holdntrade.log = mock_logging
        holdntrade.exchange = holdntrade.connect_to_exchange(holdntrade.conf)
        holdntrade.curr_buy_order = holdntrade.Order({'side': 'buy', 'id': '1B', 'price': 15000, 'amount': 222,
                                                      'datetime': datetime.datetime.today().isoformat()})
        holdntrade.buy_orders.append(holdntrade.curr_buy_order)

        holdntrade.curr_buy_order_size = 222
        market_price = 9000
        mock_fetch_ticker.return_value = {'bid': market_price}
        mock_fetch_balance.return_value = {'BTC': {'used': 300, 'free': 400, 'total': 700}}
        mock_fetch_order_status.return_value = 'closed'
        price = 9999
        buy_price = round(price * (1 - holdntrade.conf.change))
        sell_price = round(price * (1 + holdntrade.conf.change))

        holdntrade.buy_executed(price, 100)

        mock_logging.debug.assert_called()
        mock_logging.warning.assert_not_called()
        mock_create_limit_sell_order.assert_called_with(holdntrade.conf.pair, 222, sell_price)
        mock_create_limit_buy_order.assert_called_with(holdntrade.conf.pair, 100, buy_price)

    @patch('holdntrade.logging')
    @patch('holdntrade.get_used_balance')
    @mock.patch.object(ccxt.bitmex, 'create_limit_sell_order')
    def test_create_divided_sell_order(self, mock_create_limit_sell_order, mock_get_used_balance, mock_logging):
        holdntrade.conf = self.create_default_conf()
        holdntrade.conf.base = 'BTC'
        holdntrade.log = mock_logging
        holdntrade.exchange = holdntrade.connect_to_exchange(holdntrade.conf)
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
        holdntrade.exchange = holdntrade.connect_to_exchange(holdntrade.conf)

        holdntrade.spread(market_price)

        mock_fetch_order_status.assert_called_with(buy2.id)
        mock_cancel_order.assert_called_with(buy2.id)
        mock_create_limit_buy_order.assert_called_with('BTC/USD', 102, buy_price)
        mock_create_limit_sell_order.assert_called_with('BTC/USD', 102, sell_price)
        self.assertTrue(len(holdntrade.buy_orders) == 2)
        self.assertTrue(holdntrade.buy_price == buy_price)
        self.assertTrue(len(holdntrade.sell_orders) == 3)

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
        conf.mm_stop_buy = 2.3
        conf.auto_leverage = False
        conf.leverage_default = 2
        return conf


if __name__ == '__main__':
    unittest.main()
