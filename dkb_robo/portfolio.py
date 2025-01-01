""" Module for handling dkb transactions """
# pylint: disable=c0415, r0913
from typing import Dict, List, Tuple
import logging
import requests
from dkb_robo.utilities import get_dateformat

LEGACY_DATE_FORMAT, API_DATE_FORMAT = get_dateformat()
BASE_URL = 'https://banking.dkb.de/api'
logger = logging.getLogger(__name__)


class ProductGroup:
    """ ProductGroup class"""

    def _uid2names(self, data_ele: Dict[str, str]) -> Dict[str, str]:
        """ create a dictionary containing id to product-name mapping """
        logger.debug('ProductGroup._uid2names()\n')

        product_settings_dic = {}
        portfolio_dic = data_ele.get('attributes', {}).get('productSettings', {})
        for product_data in portfolio_dic.values():
            if isinstance(product_data, dict):
                for uid, product_value in product_data.items():
                    if 'name' in product_value:
                        product_settings_dic[uid] = product_value['name']
            else:
                logger.warning('uid2name mapping failed. product data are not in dictionary format')

        logger.debug('ProductGroup._uid2names() ended\n')
        return product_settings_dic

    def _group(self, data_ele: Dict[str, str]) -> List[str]:
        """ create a list of products per group """
        logger.debug('ProductGroup._group()\n')

        product_group_list = []
        portfolio_dic = data_ele.get('attributes', {}).get('productGroups', {})
        for product_group in sorted(portfolio_dic.values(), key=lambda x: x['index']):
            id_dic = {}
            for _id_dic in product_group['products'].values():
                for uid in _id_dic:
                    id_dic[_id_dic[uid]['index']] = uid
            product_group_list.append({'name': product_group['name'], 'product_list': id_dic})

        logger.debug('ProductGroup._group()\n')
        return product_group_list

    def map(self, data_ele: Dict[str, str]) -> Tuple[Dict[str, str], Dict[str, str], int]:
        """ fetch data """
        logger.debug('ProductGroup.map()\n')

        # crate uid-name mapping and items per product group needed to sort the productgroup
        return self._uid2names(data_ele), self._group(data_ele)


class Overview:
    """ Overview class """

    def __init__(self, client: requests.Session, base_url: str = BASE_URL):
        self.client = client
        self.base_url = base_url

    def _add_remaining(self, data_dic: Dict[str, str], account_dic: Dict[str, str], account_cnt: int) -> Dict[str, str]:
        """ add remaining products """
        logger.debug('Overview._add_remaining()\n')

        for product_data in data_dic.values():
            account_dic[account_cnt] = product_data
            account_dic[account_cnt]['productgroup'] = None
            account_cnt += 1

        logger.debug('Overview._add_remaining() ended\n')
        return account_dic

    def _fetch(self, url_path) -> Dict[str, str]:
        """ fetch data via API """
        logger.debug('Overview._fetch()\n')

        response = self.client.get(self.base_url + url_path)
        if response.status_code == 200:
            response_dic = response.json()
        else:
            logger.error('fetch %s: RC is not 200 but %s', url_path, response.status_code)
            response_dic = {}

        logger.debug('Overview._fetch() ended\n')
        return response_dic

    def _sort(self, portfolio_dic: Dict[str, str]) -> Dict[str, str]:
        """ format and sort data """
        logger.debug('Overview._sort()\n')

        account_dic = {}
        account_cnt = 0

        data_dic = self._itemize(portfolio_dic)

        display_settings_dic = portfolio_dic.get('product_display', {}).get('data', {})
        productgroup = ProductGroup()
        for portfolio in display_settings_dic:
            # get id/name mapping and productlist per group
            product_display_dic, product_group_list = productgroup.map(portfolio)
            for product_group in product_group_list:
                # dic_id is a uid of the product
                for dic_id in sorted(product_group['product_list']):
                    if product_group['product_list'][dic_id] in data_dic:
                        logger.debug('Overview._sort(): assign productgroup "%s" to product %s', product_group['name'], product_group['product_list'][dic_id])
                        # add product data to account_dic
                        account_dic[account_cnt] = data_dic[product_group['product_list'][dic_id]]
                        # add productgroup name to account_dic
                        account_dic[account_cnt]['productgroup'] = product_group['name']

                        if product_group['product_list'][dic_id] in product_display_dic:
                            logger.debug('Overview._sort(): found displayname "%s" for product %s', product_display_dic[product_group['product_list'][dic_id]], product_group['product_list'][dic_id])
                            # overwrite product name with display name
                            account_dic[account_cnt]['name'] = product_display_dic[product_group['product_list'][dic_id]]

                        del data_dic[product_group['product_list'][dic_id]]
                        account_cnt += 1

        # add products without productgroup
        account_dic = self._add_remaining(data_dic, account_dic, account_cnt)

        logger.debug('Overview._sort() ended\n')
        return account_dic

    def _itemize(self, portfolio_dic: Dict[str, str]) -> Dict[str, str]:
        """ raw data """
        logger.debug('Overview._itemize()\n')

        product_dic = {}

        product_group_dic = {
            'accounts': Account(self.base_url),
            'cards': Card(self.base_url),
            'depots': Depot(self.base_url)
        }
        for product_group in sorted(product_group_dic.keys()):
            if product_group in portfolio_dic and 'data' in portfolio_dic[product_group]:
                product_group_object = product_group_dic[product_group]
                for item in portfolio_dic[product_group]['data']:
                    if 'id' in item and 'type' in item:
                        product_dic[item['id']] = product_group_object.get(item['id'], portfolio_dic[product_group])

        logger.debug('Overview._itemize() ended\n')
        return product_dic

    def get(self):
        """ Get overview """
        logger.debug('Overview.get()')

        # we calm the IDS system of DKB with two calls without sense
        # self._fetch('/terms-consent/consent-requests??filter%5Bportfolio%5D=DKB')
        product_display_dic = self._fetch('/config/users/me/product-display-settings')

        if product_display_dic:
            portfolio_dic = {
                'product_display': product_display_dic,
                'accounts': self._fetch('/accounts/accounts'),
                'cards': self._fetch('/credit-card/cards?filter%5Btype%5D=creditCard&filter%5Bportfolio%5D=dkb&filter%5Btype%5D=debitCard'),
                'depots': self._fetch('/broker/brokerage-accounts'),
                'loans': self._fetch('/loans/loans')
            }
        else:
            portfolio_dic = {}

        logger.debug('Overview.get() ended\n')
        return self._sort(portfolio_dic)


class Account:
    """ Account class """

    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url

    def _balance(self, account: Dict[str, str]) -> Dict[str, str]:
        """ add balance to dictionary """
        logger.debug('Account._balance()\n')

        output_dic = {}
        mapping_dic = {'amount': 'value', 'currencycode': 'currencyCode'}
        for my_field, dkb_field in mapping_dic.items():
            if my_field == 'amount':
                try:
                    output_dic[my_field] = float(account.get('attributes', {}).get('balance', {}).get(dkb_field, None))
                except Exception as exc:
                    logger.error('account amount conversion error: %s', exc)
                    output_dic[my_field] = None
            else:
                output_dic[my_field] = account.get('attributes', {}).get('balance', {}).get(dkb_field, None)

        logger.debug('Account._balance() ended\n')
        return output_dic

    def _details(self, account: Dict[str, str], aid: str) -> Dict[str, str]:
        """ add general account information """
        logger.debug('Account._details()\n')

        output_dic = {
            'type': 'account',
            'name': account.get('attributes', {}).get('product', {}).get('displayName', None),
            'id': aid,
            'transactions': self.base_url + f"/accounts/accounts/{aid}/transactions",
            'date': account.get('attributes', {}).get('updatedAt', None)
        }

        mapping_dic = {'iban': 'iban', 'account': 'iban', 'holdername': 'holderName', 'limit': 'overdraftLimit'}
        for my_field, dkb_field in mapping_dic.items():
            if my_field == 'limit':
                try:
                    output_dic[my_field] = float(account.get('attributes', {}).get(dkb_field, 0))
                except Exception as exc:
                    logger.error('account limit conversion error: %s', exc)
                    output_dic[my_field] = None
            else:
                output_dic[my_field] = account.get('attributes', {}).get(dkb_field, None)

        logger.debug('Account._details() ended\n')
        return output_dic

    def get(self, aid: str, accounts_dic: Dict[str, str]) -> Dict[str, str]:
        """ get account """
        logger.debug('Account.get(%s)', aid)

        output_dic = {}
        if 'data' in accounts_dic:
            for account in accounts_dic['data']:
                if account['id'] == aid and 'attributes' in account:
                    # build dictionary with account information
                    output_dic = {**self._details(account, aid), **self._balance(account)}
                    break

        logger.debug('Account.get() ended\n')
        return output_dic


class Card:
    """ Card class """

    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url

    def _balance(self, card: Dict[str, str]) -> Dict[str, str]:
        """ add card balance to dictionary """
        logger.debug('Card._balance()\n')

        if 'balance' in card['attributes']:
            # DKB shows card balance in a weired way
            try:
                amount = float(card.get('attributes', {}).get('balance', {}).get('value', None)) * -1
            except Exception as exc:
                logger.error('card amount conversion error: %s', exc)
                amount = None

            output_dic = {
                'amount': amount,
                'currencycode': card.get('attributes', {}).get('balance', {}).get('currencyCode', None),
                'date': card.get('attributes', {}).get('balance', {}).get('date', None)
            }
        else:
            output_dic = {}

        logger.debug('Card._balance() ended\n')
        return output_dic

    def _details(self, card: Dict[str, str], cid: str) -> Dict[str, str]:
        """ add general information of card """
        logger.debug('Card._details()\n')

        try:
            limit = float(card.get('attributes', {}).get('limit', {}).get('value', 0))
        except Exception as exc:
            logger.error('card limit conversion error: %s', exc)
            limit = None

        output_dic = {
            'id': cid,
            'type': card.get('type', 'unknown').lower(),
            'maskedpan': card.get('attributes', {}).get('maskedPan', None),
            'account': card.get('attributes', {}).get('maskedPan', None),
            'status': card.get('attributes', {}).get('status', None),
            'name': card.get('attributes', {}).get('product', {}).get('displayName', None),
            'expirydate': card.get('attributes', {}).get('expiryDate', None),
            'holdername': f"{card.get('attributes', {}).get('holder', {}).get('person', {}).get('firstName', '')} {card.get('attributes', {}).get('holder', {}).get('person', {}).get('lastName', '')}"
        }

        if card['type'] == 'debitCard':
            output_dic['transactions'] = None
        else:
            output_dic['transactions'] = self.base_url + f"/credit-card/cards/{cid}/transactions"
            output_dic['limit'] = limit

        logger.debug('Card._details() ended\n')
        return output_dic

    def get(self, cid: str, cards_dic: Dict[str, str]) -> Dict[str, str]:
        """ get credit card """
        logger.debug('Card.get(%s)', cid)

        output_dic = {}
        if 'data' in cards_dic:
            for card in cards_dic['data']:
                if card['id'] == cid and 'attributes' in card:
                    # build dictionary with card information
                    output_dic = {**self._details(card, cid), **self._balance(card)}
                    break

        logger.debug('Card.get() ended\n')
        return output_dic


class Depot:
    """ Depot class """

    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url

    def _balance(self, depot: Dict[str, str]) -> Dict[str, str]:
        """ add depot value and currentcy """
        logger.debug('Depot._balance()\n')

        try:
            amount = float(depot.get('attributes', {}).get('brokerageAccountPerformance', {}).get('currentValue', {}).get('value', None))
        except Exception as exc:
            logger.error('depot amount conversion error: %s', exc)
            amount = None

        output_dic = {
            'amount': amount,
            'currencycode': depot.get('attributes', {}).get('brokerageAccountPerformance', {}).get('currentValue', {}).get('currencyCode', None)
        }

        logger.debug('Depot._balance() ended\n')
        return output_dic

    def _details(self, depot: Dict[str, str], did: str) -> Dict[str, str]:
        """ add depot information """
        logger.debug('Depot._details()\n')

        output_dic = {
            'type': 'depot',
            'id': did,
            'transactions': self.base_url + f"/broker/brokerage-accounts/{did}/positions?include=instrument%2Cquote",
            'holdername': depot.get('attributes', {}).get('holderName', None),
            'account': depot.get('attributes', {}).get('depositAccountId', None),
            'name': depot.get('attributes', {}).get('holderName', None),
        }

        logger.debug('Depot._details() ended\n')
        return output_dic

    def get(self, did: str, depots_dic: Dict[str, str]) -> Dict[str, str]:
        """ get depot """
        logger.debug('Depot.get(%s)', did)

        output_dic = {}
        if 'data' in depots_dic:
            for depot in depots_dic['data']:
                if depot['id'] == did and 'attributes' in depot:
                    output_dic = {**self._details(depot, did), **self._balance(depot)}
                    break

        logger.debug('Depot.get() ended\n')
        return output_dic
