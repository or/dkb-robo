""" legacy api """
# -*- coding: utf-8 -*-
# pylint: disable=r0913
import os
import datetime
import time
import logging
import json
from typing import Dict, List, Tuple
import requests
from dkb_robo.utilities import get_dateformat


LEGACY_DATE_FORMAT, API_DATE_FORMAT = get_dateformat()


class DKBRoboError(Exception):
    """ dkb-robo exception class """
    ...


class Wrapper(object):
    """ this is the wrapper for the legacy api """
    base_url = 'https://banking.dkb.de'
    api_prefix = '/api'
    mfa_method = 'seal_one'
    dkb_user = None
    dkb_password = None
    # dkb_br = None
    logger = None
    proxies = {}
    client = None
    token_dic = None
    account_dic = {}

    def __init__(self, dkb_user: str = None, dkb_password: str = None, proxies: Dict[str, str] = None, logger: logging.Logger = False):
        self.dkb_user = dkb_user
        self.dkb_password = dkb_password
        self.proxies = proxies
        self.logger = logger

    def _add_account_transactionamount(self, transaction):
        """ add amount from accont transaction """
        self.logger.debug('api.Wrapper._add_account_transactionamount()\n')

        output_dic = {}
        if 'amount' in transaction['attributes']:
            if 'value' in transaction['attributes']['amount']:
                output_dic['amount'] = float(transaction['attributes']['amount']['value'])
            if 'currencyCode' in transaction['attributes']['amount']:
                output_dic['currencycode'] = transaction['attributes']['amount']['currencyCode']

        return output_dic

    def _add_account_transaction_creditorinfo(self, transaction):
        """ we need creditor information for outgoing payments"""
        self.logger.debug('api.Wrapper._add_account_transaction_creditorinfo()\n')

        output_dic = {}
        if 'creditor' in transaction['attributes']:
            if 'creditorAccount' in transaction['attributes']['creditor'] and 'iban' in transaction['attributes']['creditor']['creditorAccount']:
                output_dic['peeraccount'] = transaction['attributes']['creditor']['creditorAccount']['iban']
            if 'agent' in transaction['attributes']['creditor'] and 'bic' in transaction['attributes']['creditor']['agent']:
                output_dic['peerbic'] = transaction['attributes']['creditor']['agent']['bic']
            if 'name' in transaction['attributes']['creditor']:
                output_dic['peer'] = transaction['attributes']['creditor']['name']
            if 'id' in transaction['attributes']['creditor']:
                output_dic['peerid'] = transaction['attributes']['creditor']['id']
            else:
                output_dic['peerid'] = ''

        return output_dic

    def _add_account_transaction_debtorinfo(self, transaction):
        """we need debitor information for incoming payments """
        self.logger.debug('api.Wrapper._add_account_transaction_debtorinfo()\n')

        output_dic = {}
        if 'debtor' in transaction['attributes']:
            if 'debtorAccount' in transaction['attributes']['debtor'] and 'iban' in transaction['attributes']['debtor']['debtorAccount']:
                output_dic['peeraccount'] = transaction['attributes']['debtor']['debtorAccount']['iban']
            if 'agent' in transaction['attributes']['debtor'] and 'bic' in transaction['attributes']['debtor']['agent']:
                output_dic['peerbic'] = transaction['attributes']['debtor']['agent']['bic']
            if 'intermediaryName' in transaction['attributes']['debtor'] and transaction['attributes']['debtor']['intermediaryName']:
                output_dic['peer'] = transaction['attributes']['debtor']['intermediaryName']
            else:
                if 'name' in transaction['attributes']['debtor']:
                    output_dic['peer'] = transaction['attributes']['debtor']['name']

            # add perrid
            output_dic['peerid'] = self._add_account_transaction_debtorpeerid(transaction)

        return output_dic

    def _add_account_transaction_debtorpeerid(self, transaction):
        """ lookup peerid """
        self.logger.debug('api.Wrapper._add_account_transaction_debtorpeerid()\n')
        peer_id = ''
        if 'id' in transaction['attributes']['debtor']:
            peer_id = transaction['attributes']['debtor']['id']

        return peer_id

    def _add_account_transactioninformation(self, transaction):
        """ add infromation from accont transaction """
        self.logger.debug('api.Wrapper._add_account_transactioninformation()\n')

        output_dic = {}
        if 'bookingDate' in transaction['attributes']:
            output_dic['date'] = transaction['attributes']['bookingDate']
            output_dic['bdate'] = transaction['attributes']['bookingDate']
        if 'valueDate' in transaction['attributes']:
            output_dic['vdate'] = transaction['attributes']['valueDate']
        if 'endToEndId' in transaction['attributes']:
            output_dic['customerreference'] = transaction['attributes']['endToEndId']
        if 'mandateId' in transaction['attributes']:
            output_dic['mandatereference'] = transaction['attributes']['mandateId']
        if 'transactionType' in transaction['attributes']:
            output_dic['postingtext'] = transaction['attributes']['transactionType']
        if 'description' in transaction['attributes']:
            output_dic['reasonforpayment'] = transaction['attributes']['description']

        return output_dic

    def _get_account_details(self, aid, accounts_dic):
        """ get credit account details from cc json """
        self.logger.debug('api.Wrapper._get_account_details(%s)\n', aid)

        output_dic = {}
        if 'data' in accounts_dic:
            for account in accounts_dic['data']:
                if account['id'] == aid and 'attributes' in account:
                    # build dictionary with account information
                    output_dic = {**self._add_accountinformation(account, aid), **self._add_accountdetails(account), **self._add_accountbalance(account), **self._add_accountname(account)}
                    break

        return output_dic

    def _add_accountbalance(self, account):
        """ add balance to dictionary """
        self.logger.debug('api.Wrapper._add_accountbalance()\n')

        output_dic = {}
        if 'balance' in account['attributes']:
            mapping_dic = {'amount': 'value', 'currencycode': 'currencyCode'}
            for my_field, dkb_field in mapping_dic.items():
                if dkb_field in account['attributes']['balance']:
                    output_dic[my_field] = account['attributes']['balance'][dkb_field]

        return output_dic

    def _add_accountdetails(self, account):
        """ add several details to dictionaries """
        self.logger.debug('api.Wrapper._add_accountdetails()\n')

        output_dic = {}
        mapping_dic = {'iban': 'iban', 'account': 'iban', 'holdername': 'holderName', 'limit': 'overdraftLimit'}
        for my_field, dkb_field in mapping_dic.items():
            if dkb_field in account['attributes']:
                output_dic[my_field] = account['attributes'][dkb_field]

        return output_dic

    def _add_accountinformation(self, account, aid):
        """ add general account information """
        self.logger.debug('api.Wrapper._add_accountinformation()\n')

        output_dic = {}
        output_dic['type'] = 'account'
        output_dic['id'] = aid
        output_dic['transactions'] = self.base_url + self.api_prefix + f"/accounts/accounts/{aid}/transactions"
        if 'updatedAt' in account['attributes']:
            output_dic['date'] = account['attributes']['updatedAt']
        return output_dic

    def _add_accountname(self, account):
        """ add card name """
        self.logger.debug('api.Wrapper._add_accountname()\n')

        output_dic = {'name': account['attributes']['product']['displayName']}

        return output_dic

    def _add_brokerage_informationy(self, position):
        """ add lastorder date and value """
        self.logger.debug('api.Wrapper._add_brokerage_informationy()\n')

        output_dic = {}
        if 'lastOrderDate' in position['attributes']:
            output_dic['lastorderdate'] = position['attributes']['lastOrderDate']

        if 'performance' in position['attributes'] and 'currentValue' in position['attributes']['performance'] and 'value' in position['attributes']['performance']['currentValue']:
            output_dic['price_euro'] = position['attributes']['performance']['currentValue']['value']

        return output_dic

    def _add_brokerage_instrumentinformation(self, ele):
        """ add instrument information """
        self.logger.debug('api.Wrapper._add_brokerage_instrumentinformation()\n')

        output_dic = {}
        if 'attributes' in ele:
            if 'name' in ele['attributes'] and 'short' in ele['attributes']['name']:
                output_dic['text'] = ele['attributes']['name']['short']
            if 'identifiers' in ele['attributes']:
                for identifier in ele['attributes']['identifiers']:
                    if identifier['identifier'] == 'isin':
                        output_dic['isin_wkn'] = identifier['value']
                        break
        return output_dic

    def _add_brokerage_quoteinformation(self, ele):
        """ add quote information """
        self.logger.debug('api.Wrapper._add_brokerage_quoteinformation()\n')

        output_dic = {}
        if 'attributes' in ele and 'price' in ele['attributes']:
            if 'value' in ele['attributes']['price']:
                output_dic['price'] = float(ele['attributes']['price']['value'])
            if 'currencyCode' in ele['attributes']['price']:
                output_dic['currencycode'] = ele['attributes']['price']['currencyCode']
        if 'market' in ele['attributes']:
            output_dic['market'] = ele['attributes']['market']

        return output_dic

    def _add_brokerage_quantity(self, position):
        """ add quantity information """
        self.logger.debug('api.Wrapper._add_brokerage_quantity()\n')
        output_dic = {}
        if 'quantity' in position['attributes']:
            output_dic['shares'] = position['attributes']['quantity']['value']
            output_dic['quantity'] = float(position['attributes']['quantity']['value'])
            output_dic['shares_unit'] = position['attributes']['quantity']['unit']

        return output_dic

    def _add_brokerageholder(self, depot):
        """ add card holder information """
        self.logger.debug('api.Wrapper._add_brokerageholder()\n')

        output_dic = {'name': depot['attributes']['holderName']}
        return output_dic

    def _add_brokerageinformation(self, depot, bid):
        """ add depot information """
        self.logger.debug('api.Wrapper._add_brokerageinformation()\n')

        output_dic = {}
        output_dic['type'] = 'depot'
        output_dic['id'] = bid
        output_dic['transactions'] = self.base_url + self.api_prefix + f"/broker/brokerage-accounts/{bid}/positions?include=instrument%2Cquote"
        if 'holderName' in depot['attributes']:
            output_dic['holdername'] = depot['attributes']['holderName']
        if 'depositAccountId' in depot['attributes']:
            output_dic['account'] = depot['attributes']['depositAccountId']

        return output_dic

    def _add_brokerageperformance(self, depot):
        """ add depot value and currentcy """
        self.logger.debug('api.Wrapper._add_brokerage_performance()\n')

        output_dic = {}
        if 'brokerageAccountPerformance' in depot['attributes']:
            if 'currentValue' in depot['attributes']['brokerageAccountPerformance']:
                if 'currencyCode' in depot['attributes']['brokerageAccountPerformance']['currentValue']:
                    output_dic['currencycode'] = depot['attributes']['brokerageAccountPerformance']['currentValue']['currencyCode']
                if 'value' in depot['attributes']['brokerageAccountPerformance']['currentValue']:
                    output_dic['amount'] = depot['attributes']['brokerageAccountPerformance']['currentValue']['value']

        return output_dic

    def _add_card_transactionamount(self, transaction):
        """ add amount from card transaction """
        self.logger.debug('api.Wrapper._add_card_transactionamount()\n')
        output_dic = {}
        if 'amount' in transaction['attributes']:
            if 'value' in transaction['attributes']['amount']:
                output_dic['amount'] = float(transaction['attributes']['amount']['value'])
            if 'currencyCode' in transaction['attributes']['amount']:
                output_dic['currencycode'] = transaction['attributes']['amount']['currencyCode']

        return output_dic

    def _add_cardbalance(self, card):
        """ add card balance to dictionary """
        self.logger.debug('api.Wrapper._add_cardbalance()\n')

        output_dic = {}
        if 'balance' in card['attributes']:
            # DKB show it in a weired way
            if 'value' in card['attributes']['balance']:
                output_dic['amount'] = float(card['attributes']['balance']['value']) * -1
            if 'currencyCode' in card['attributes']['balance']:
                output_dic['currencycode'] = card['attributes']['balance']['currencyCode']
            if 'date' in card['attributes']['balance']:
                output_dic['date'] = card['attributes']['balance']['date']

        return output_dic

    def _add_cardholder(self, card):
        """ add card holder information """
        self.logger.debug('api.Wrapper._add_cardholder()\n')

        output_dic = {}
        if 'holder' in card['attributes'] and 'person' in card['attributes']['holder']:
            if 'firstName' in card['attributes']['holder']['person'] and 'lastName' in card['attributes']['holder']['person']:
                output_dic['holdername'] = f"{card['attributes']['holder']['person']['firstName']} {card['attributes']['holder']['person']['lastName']}"

        return output_dic

    def _add_cardinformation(self, card, cid):
        """ add general information of card """
        self.logger.debug('api.Wrapper._add_cardinformation()\n')

        output_dic = {}
        output_dic['id'] = cid

        if 'type' in card:
            output_dic['type'] = card['type'].lower()
            if card['type'] == 'debitCard':
                output_dic['transactions'] = None
            else:
                output_dic['transactions'] = self.base_url + self.api_prefix + f"/credit-card/cards/{cid}/transactions"

        if 'maskedPan' in card['attributes']:
            output_dic['maskedpan'] = card['attributes']['maskedPan']
            output_dic['account'] = card['attributes']['maskedPan']
        if 'status' in card['attributes']:
            output_dic['status'] = card['attributes']['status']

        return output_dic

    def _add_cardlimit(self, card):
        """ add cardlimit and expiry date """
        self.logger.debug('api.Wrapper._add_cardlimit()\n')

        output_dic = {}
        if 'expiryDate' in card['attributes']:
            output_dic['expirydate'] = card['attributes']['expiryDate']

        if 'limit' in card['attributes'] and 'value' in card['attributes']['limit']:
            output_dic['limit'] = card['attributes']['limit']['value']

        return output_dic

    def _add_card_transactioninformation(self, transaction):
        """ add card transaction infromatoin """
        self.logger.debug('api.Wrapper._add_card_transactioninformation()\n')
        output_dic = {}
        if 'bookingDate' in transaction['attributes']:
            output_dic['bdate'] = transaction['attributes']['bookingDate']
            output_dic['vdate'] = transaction['attributes']['bookingDate']
        if 'description' in transaction['attributes']:
            output_dic['text'] = transaction['attributes']['description']
        return output_dic

    def _add_cardname(self, card):
        """ add card name """
        self.logger.debug('api.Wrapper._add_cardname()\n')

        output_dic = {'name': card['attributes']['product']['displayName']}

        return output_dic

    def _raw_entry_get(self, portfolio_dic, product_group, ele):
        """ sort products and get details """
        self.logger.debug('api.Wrapper._raw_entry_get()\n')

        if ele['type'] == 'brokerageAccount':
            result = self._get_brokerage_details(ele['id'], portfolio_dic[product_group])
        elif 'Card' in ele['type']:
            result = self._get_card_details(ele['id'], portfolio_dic[product_group])
        elif 'account' in ele['type']:
            result = self._get_account_details(ele['id'], portfolio_dic[product_group])

        return result

    def _build_raw_account_dic(self, portfolio_dic):
        """ sort products and get details """
        self.logger.debug('api.Wrapper._build_raw_account_dic()\n')
        product_dic = {}

        for product_group in ['accounts', 'cards', 'brokerage_accounts']:
            if product_group in portfolio_dic and 'data' in portfolio_dic[product_group]:
                for ele in portfolio_dic[product_group]['data']:
                    if 'id' in ele and 'type' in ele:
                        product_dic[ele['id']] = self._raw_entry_get(portfolio_dic, product_group, ele)

        return product_dic

    def _build_account_dic_from_pd(self, data_ele, account_dic, _raw_account_dic, account_cnt):
        """ build account dic based on product_display dictionary"""
        self.logger.debug('api.Wrapper._build_account_dic_from_pd()\n')

        # build product settings dictioary needed to sort the productgroup
        product_display_dic = self._build_product_display_settings_dic(data_ele)
        product_group_list = self._build_product_group_list(data_ele)
        for product_group in product_group_list:
            for dic_id in sorted(product_group['product_list']):
                if product_group['product_list'][dic_id] in _raw_account_dic:
                    self.logger.debug('api.Wrapper._build_account_dic(): found "%s" %s in account_list', product_group['name'], dic_id)
                    account_dic[account_cnt] = _raw_account_dic[product_group['product_list'][dic_id]]
                    account_dic[account_cnt]['productgroup'] = product_group['name']
                    if product_group['product_list'][dic_id] in product_display_dic:
                        self.logger.debug('api.Wrapper._build_account_dic(): found "%s" in product_display_dic', product_group['product_list'][dic_id])
                        account_dic[account_cnt]['name'] = product_display_dic[product_group['product_list'][dic_id]]
                    del _raw_account_dic[product_group['product_list'][dic_id]]
                    account_cnt += 1

        return account_dic, _raw_account_dic, account_cnt

    def _build_account_dic(self, portfolio_dic):
        """ create overview """
        self.logger.debug('api.Wrapper._build_account_dic()\n')

        account_dic = {}
        account_cnt = 0

        _raw_account_dic = self._build_raw_account_dic(portfolio_dic)

        if 'product_display' in portfolio_dic and 'data' in portfolio_dic['product_display']:
            for data_ele in portfolio_dic['product_display']['data']:
                account_dic, _raw_account_dic, account_cnt = self._build_account_dic_from_pd(data_ele, account_dic, _raw_account_dic, account_cnt)

        for _id, product_data in _raw_account_dic.items():
            account_dic[account_cnt] = product_data
            account_dic[account_cnt]['productgroup'] = None
            account_cnt += 1

        return account_dic

    def _build_product_group_list_index(self, product_group):
        """ build index for group sorting """
        self.logger.debug('api.Wrapper._build_product_group_list_index()\n')
        id_dic = {}
        for _id_dic in product_group['products'].values():
            for uid in _id_dic:
                id_dic[_id_dic[uid]['index']] = uid

        return id_dic

    def _build_product_group_list(self, data_ele):
        """ buuild list of product grups including objects """
        product_group_list = []
        if 'attributes' in data_ele:
            if 'productGroups' in data_ele['attributes'] and data_ele['attributes']['productGroups']:
                # sorting should be similar to frontend
                for product_group in sorted(data_ele['attributes']['productGroups'].values(), key=lambda x: x['index']):
                    product_group_list.append({'name': product_group['name'], 'product_list': self._build_product_group_list_index(product_group)})

        return product_group_list

    def _build_product_name_dic(self, product_data):
        self.logger.debug('api.Wrapper._build_product_display_items()\n')

        uid_dic = {}
        if isinstance(product_data, dict):
            for uid, product_value in product_data.items():
                if 'name' in product_value:
                    uid_dic[uid] = product_value['name']
                else:
                    self.logger.error('api.Wrapper._build_product_display_settings_dic(): "name" key not found')
        else:
            self.logger.error('api.Wrapper._build_product_display_settings_dic(): product_data is not of type dic')

        return uid_dic

    def _build_product_display_settings_dic(self, data_ele):
        """ build products settings dictionary """
        self.logger.debug('api.Wrapper._build_product_display_settings_dic()\n')

        product_settings_dic = {}
        if 'attributes' in data_ele and 'productSettings' in data_ele['attributes']:
            for _product, product_data in data_ele['attributes']['productSettings'].items():
                prod_name_dic = self._build_product_name_dic(product_data)
                if prod_name_dic:
                    product_settings_dic = {**product_settings_dic, **prod_name_dic}

        return product_settings_dic

    def _check_processing_status(self, polling_dic, cnt):
        self.logger.debug('api.Wrapper._check_processing_status()\n')
        self.logger.debug('api.Wrapper._login: cnt %s got %s flag', cnt, polling_dic['data']['attributes']['verificationStatus'])

        mfa_completed = False
        if (polling_dic['data']['attributes']['verificationStatus']) == 'processed':
            mfa_completed = True
        elif (polling_dic['data']['attributes']['verificationStatus']) == 'canceled':
            raise DKBRoboError('2fa chanceled by user')
        return mfa_completed

    def _complete_2fa(self, challenge_id, devicename):
        """ wait for confirmation for the 2nd factor """
        self.logger.debug('api.Wrapper._complete_2fa()\n')

        self._print_2fa_confirmation(devicename)

        cnt = 0
        mfa_completed = False
        # we give us 50 seconds to press a button on the phone
        while cnt <= 10:
            response = self.client.get(self.base_url + self.api_prefix + f"/mfa/mfa/challenges/{challenge_id}")
            cnt += 1
            if response.status_code == 200:
                polling_dic = response.json()
                if 'data' in polling_dic and 'attributes' in polling_dic['data'] and 'verificationStatus' in polling_dic['data']['attributes']:
                    # check processing status
                    mfa_completed = self._check_processing_status(polling_dic, cnt)
                    if mfa_completed:
                        break
                else:
                    self.logger.error('api.Wrapper._complete_2fa(): error parsing polling response: %s', polling_dic)
            else:
                self.logger.error('api.Wrapper._complete_2fa(): polling request failed. RC: %s', response.status_code)
            time.sleep(5)

        return mfa_completed

    def _do_sso_redirect(self):
        """  redirect to access legacy page """
        self.logger.debug('api.Wrapper._do_sso_redirect()\n')

        data_dic = {'data': {'cookieDomain': '.dkb.de'}}
        self.client.headers['Content-Type'] = 'application/json'
        self.client.headers['Sec-Fetch-Dest'] = 'empty'
        self.client.headers['Sec-Fetch-Mode'] = 'cors'
        self.client.headers['Sec-Fetch-Site'] = 'same-origin'

        response = self.client.post(self.base_url + self.api_prefix + '/sso-redirect', data=json.dumps(data_dic))

        if response.status_code != 200 or response.text != 'OK':
            self.logger.error('SSO redirect failed. RC: %s text: %s', response.status_code, response.text)

        clientcookies = self.client.cookies
        self.logger.error('sso redirect disabled')
        # self.dkb_br = self._new_instance(clientcookies)

    def _download_document(self, path, document):
        """ filter standing orders """
        self.logger.debug('api.Wrapper._download_document()\n')

        # create directory if not existing
        directories = [path, f'{path}/{document["document_type"]}']
        for directory in directories:
            if not os.path.exists(directory):
                self.logger.debug('api.Wrapper._download_document(): Create directory %s\n', directory)
                os.makedirs(directory)

        if 'filename' in document and 'link' in document:

            # modify accept attribute in
            dlc = self.client
            dlc.headers['Accept'] = document['contenttype']
            response = dlc.get(document['link'])

            if document['contenttype'] == 'application/pdf' and not document['filename'].endswith('pdf'):
                self.logger.debug('api.Wrapper._download_document(): renaming %s', document['filename'])
                document['filename'] = f'{document["filename"]}.pdf'

            if response.status_code == 200:
                self.logger.info('Saving %s/%s...', directories[1], document['filename'])
                with open(f'{directories[1]}/{document["filename"]}', 'wb') as file:
                    file.write(response.content)

                if not document['read']:
                    # set document status to "read"
                    self.logger.debug('api.Wrapper._download_document() set docment to "read"\n')
                    data_dic = {"data": {"attributes": {"read": True}, "type": "message"}}
                    dlc.headers['Accept'] = 'application/vnd.api+json'
                    dlc.headers['Content-type'] = 'application/vnd.api+json'
                    _response = self.client.patch(document['link'].replace('/documents/', '/messages/'), json=data_dic)

                time.sleep(2)
            else:
                self.logger.error('api.Wrapper._download_document(): RC is not 200 but %s', response.status_code)

    def _filter_postbox(self, msg_dic, pb_dic, path=None, download_all=False, _archive=False, prepend_date=None):
        """ filter postbox """
        self.logger.debug('api.Wrapper._filter_postbox()\n')

        documents_dic = {}

        _tmp_dic = {}
        if 'data' in pb_dic:
            for document in pb_dic['data']:
                _tmp_dic[document['id']] = {
                    'filename': document['attributes']['fileName'],
                    'contenttype': document['attributes']['contentType'],
                    'date': document['attributes']['metadata']['statementDate'],
                    'name': self._objectname_lookup(document)
                }

        if 'data' in msg_dic:
            for message in msg_dic['data']:
                if message['id'] in _tmp_dic:
                    _tmp_dic[message['id']]['document_type'] = self._get_document_type(message['attributes']['documentType'])
                    _tmp_dic[message['id']]['read'] = message['attributes']['read']
                    _tmp_dic[message['id']]['archived'] = message['attributes']['archived']
                    _tmp_dic[message['id']]['link'] = self.base_url + self.api_prefix + '/documentstorage/documents/' + message['id']
                else:
                    print('nope')

        documentname_list = []
        for document in _tmp_dic.values():

            if 'read' in document:
                if download_all or not document['read']:
                    if path:
                        if prepend_date and document['filename'] in documentname_list:
                            self.logger.debug('api.Wrapper._filter_postbox(): duplicate document name. Renaming %s', document['filename'])
                            document['filename'] = f'{document["date"]}_{document["filename"]}'
                        self._download_document(path, document)
                        documentname_list.append(document['filename'])
                    document_type = document.pop('document_type')
                    if document_type not in documents_dic:
                        documents_dic[document_type] = {}
                        documents_dic[document_type]['documents'] = {}
                    documents_dic[document_type]['documents'][document['name']] = document['link']
            else:
                self.logger.error('api.Wrapper._filter_postbox(): document_dic incomplete: %s', document)

        return documents_dic

    def _filter_standing_orders(self, full_list):
        """ filter standing orders """
        self.logger.debug('api.Wrapper._filter_standing_orders()\n')

        so_list = []
        if 'data' in full_list:
            for ele in full_list['data']:
                _tmp_dic = {
                    'amount': float(ele['attributes']['amount']['value']),
                    'currencycode': ele['attributes']['amount']['currencyCode'],
                    'purpose': ele['attributes']['description'],
                    'recpipient': ele['attributes']['creditor']['name'],
                    'creditoraccount': ele['attributes']['creditor']['creditorAccount'],
                    'interval': ele['attributes']['recurrence']}
                so_list.append(_tmp_dic)
        return so_list

    def _filter_transactions(self, transaction_list, date_from, date_to, transaction_type):
        """ filter transaction by date """
        self.logger.debug('api.Wrapper._filter_transactions()\n')

        try:
            date_from_uts = int(time.mktime(datetime.datetime.strptime(date_from, LEGACY_DATE_FORMAT).timetuple()))
        except ValueError:
            date_from_uts = int(time.mktime(datetime.datetime.strptime(date_from, API_DATE_FORMAT).timetuple()))

        try:
            date_to_uts = int(time.mktime(datetime.datetime.strptime(date_to, LEGACY_DATE_FORMAT).timetuple()))
        except ValueError:
            date_to_uts = int(time.mktime(datetime.datetime.strptime(date_to, API_DATE_FORMAT).timetuple()))

        filtered_transaction_list = []
        for transaction in transaction_list:
            if 'attributes' in transaction and 'status' in transaction['attributes'] and 'bookingDate' in transaction['attributes']:
                if transaction['attributes']['status'] == transaction_type:
                    bookingdate_uts = int(time.mktime(datetime.datetime.strptime(transaction['attributes']['bookingDate'], API_DATE_FORMAT).timetuple()))
                    if date_from_uts <= bookingdate_uts <= date_to_uts:
                        filtered_transaction_list.append(transaction)

        return filtered_transaction_list

    def _format_account_transactions(self, transaction_list):
        """ format transactions """
        self.logger.debug('api.Wrapper._format_transactions()\n')

        format_transaction_list = []
        for transaction in transaction_list:
            if 'attributes' in transaction:
                transaction_dic = {**self._add_account_transactionamount(transaction), **self._add_account_transactioninformation(transaction)}

                if transaction_dic['amount'] > 0:
                    # incoming payment - collect debitor information
                    transaction_dic = {**transaction_dic, **self._add_account_transaction_debtorinfo(transaction)}
                else:
                    # outgoing payment - collect creditor information
                    transaction_dic = {**transaction_dic, **self._add_account_transaction_creditorinfo(transaction)}

                # add posting test for backwards compability
                if 'postingtext' in transaction_dic and 'peer' in transaction_dic and 'reasonforpayment' in transaction_dic:
                    transaction_dic['text'] = f'{transaction_dic["postingtext"]} {transaction_dic["peer"]} {transaction_dic["reasonforpayment"]}'

                format_transaction_list.append(transaction_dic)

        return format_transaction_list

    def _format_brokerage_account(self, brokerage_dic):
        """ format brokerage dictionary """
        self.logger.debug('api.Wrapper._format_brokerage_account(%s)\n', len(brokerage_dic))

        position_list = []
        included_list = self._get_brokerage_includedlist(brokerage_dic)
        if 'data' in brokerage_dic:
            for position in brokerage_dic['data']:
                position_dic = self._get_brokerage_position(position, included_list)
                if position_dic:
                    position_list.append(position_dic)

        return position_list

    def _format_card_transactions(self, transaction_list):
        """ format credit card transactions """
        self.logger.debug('api.Wrapper._format_card_transactions(%s)\n', len(transaction_list))

        format_transaction_list = []
        for transaction in transaction_list:
            if 'attributes' in transaction:
                transaction_dic = {**self._add_card_transactionamount(transaction), **self._add_card_transactioninformation(transaction)}
                format_transaction_list.append(transaction_dic)

        return format_transaction_list

    def _get_accounts(self):
        """ get accounts via API """
        self.logger.debug('api.Wrapper._get_accounts()\n')

        response = self.client.get(self.base_url + self.api_prefix + '/accounts/accounts')
        if response.status_code == 200:
            account_dic = response.json()
        else:
            self.logger.error('api.Wrapper._get_accounts(): RC is not 200 but %s', response.status_code)
            account_dic = {}

        return account_dic

    def _get_brokerage_accounts(self):
        """ get brokerage_accounts via API """
        self.logger.debug('api.Wrapper._get_brokerage_accounts()\n')

        response = self.client.get(self.base_url + self.api_prefix + '/broker/brokerage-accounts')
        if response.status_code == 200:
            account_dic = response.json()
        else:
            self.logger.error('api.Wrapper._get_brokerage_accounts(): RC is not 200 but %s', response.status_code)
            account_dic = {}

        return account_dic

    def _get_brokerage_details(self, bid, brokerage_dic):
        """ get depod details from brokerage json """
        self.logger.debug('api.Wrapper._get_brokerage_details(%s)\n', bid)

        output_dic = {}
        if 'data' in brokerage_dic:
            for depot in brokerage_dic['data']:
                if depot['id'] == bid and 'attributes' in depot:
                    output_dic = {**self._add_brokerageinformation(depot, bid), **self._add_brokerageperformance(depot), **self._add_brokerageholder(depot)}
                    break

        return output_dic

    def _get_brokerage_includedlist(self, brokerage_dic):
        """ get include list from brokerage_account dictionary"""
        self.logger.debug('api.Wrapper._get_brokerage_includedlist()\n')

        included_list = []
        if 'included' in brokerage_dic:
            included_list = brokerage_dic['included']

        return included_list

    def _get_brokerage_position(self, position, included_list):
        """ get information on a single position witin a brokerage account """
        self.logger.debug('api.Wrapper._get_brokerage_position()\n')
        (_instrument_id, _quote_id) = self._get_relationship_ids(position)

        position_dic = {}
        if 'attributes' in position:
            position_dic = {**self._add_brokerage_quantity(position), **self._add_brokerage_informationy(position)}
            for ele in included_list:
                if 'id' in ele and ele['id'] == _instrument_id:
                    position_dic = {**position_dic, **self._add_brokerage_instrumentinformation(ele)}
                if 'id' in ele and ele['id'] == _quote_id:
                    position_dic = {**position_dic, **self._add_brokerage_quoteinformation(ele)}

        return position_dic

    def _get_cards(self):
        """ get cards via API """
        self.logger.debug('api.Wrapper._get_cards()\n')

        response = self.client.get(self.base_url + self.api_prefix + '/credit-card/cards?filter%5Btype%5D=creditCard&filter%5Bportfolio%5D=dkb&filter%5Btype%5D=debitCard')
        if response.status_code == 200:
            card_dic = response.json()
        else:
            self.logger.error('api.Wrapper._get_cards(): RC is not 200 but %s', response.status_code)
            card_dic = {}

        return card_dic

    def _get_card_details(self, cid, cards_dic):
        """ get credit card details from cc json """
        self.logger.debug('api.Wrapper._get_cc_details(%s)\n', cid)

        output_dic = {}
        if 'data' in cards_dic:
            for card in cards_dic['data']:
                if card['id'] == cid and 'attributes' in card:
                    # build dictionary with card information
                    output_dic = {**self._add_cardinformation(card, cid), **self._add_cardholder(card), **self._add_cardlimit(card), **self._add_cardbalance(card), **self._add_cardname(card)}
                    break

        return output_dic

    def _get_document_name(self, doc_name):
        self.logger.debug('api.Wrapper._get_document_name()\n')

        return ' '.join(doc_name.split())

    def _get_document_type(self, doc_type):
        self.logger.debug('api.Wrapper._get_document_type()\n')
        mapping_dic = {
            'bankAccountStatement': 'Kontoauszüge',
            'creditCardStatement': 'Kreditkartenabrechnungen'
        }

        result = mapping_dic.get(doc_type, doc_type)

        return result

    def _get_loans(self):
        """ get loands via API """
        self.logger.debug('api.Wrapper._get_loans()\n')
        response = self.client.get(self.base_url + self.api_prefix + '/loans/loans')
        if response.status_code == 200:
            loans_dic = response.json()
        else:
            self.logger.error('api.Wrapper._get_loans(): RC is not 200 but %s', response.status_code)
            loans_dic = {}

        return loans_dic

    def _get_mfa_challenge_id(self, mfa_dic, device_num=0):
        """ get challenge dict with information on the 2nd factor """
        self.logger.debug('api.Wrapper._get_mfa_challenge_id() login with device_num: %s\n', device_num)

        challenge_id = None
        device_name = None

        if 'data' in mfa_dic and 'id' in mfa_dic['data'][device_num]:
            try:
                device_name = mfa_dic['data'][device_num]['attributes']['deviceName']
                self.logger.debug('api.Wrapper._get_mfa_challenge_id(): devicename: %s\n', device_name)
            except Exception as _err:
                self.logger.error('api.Wrapper._get_mfa_challenge_id(): unable to get deviceName')
                device_name = None

            # additional headers needed as this call requires it
            self.client.headers['Content-Type'] = 'application/vnd.api+json'
            self.client.headers["Accept"] = "application/vnd.api+json"

            # we are expecting the first method from mfa_dic to be used
            data_dic = {'data': {'type': 'mfa-challenge', 'attributes': {'mfaId': self.token_dic['mfa_id'], 'methodId': mfa_dic['data'][device_num]['id'], 'methodType': self.mfa_method}}}
            response = self.client.post(self.base_url + self.api_prefix + '/mfa/mfa/challenges', data=json.dumps(data_dic))

            # process response
            challenge_id = self._process_challenge_response(response)

            # we rmove the headers we added earlier
            self.client.headers.pop('Content-Type')
            self.client.headers.pop('Accept')

        else:
            self.logger.error('api.Wrapper._get_mfa_challenge_id(): mfa_dic has an unexpected data structure')

        self.logger.debug('api.Wrapper._get_mfa_challenge_id() ended\n')
        return challenge_id, device_name

    def _get_mfa_methods(self):
        """ get mfa methods """
        self.logger.debug('api.Wrapper._get_mfa_methods()\n')
        mfa_dic = {}

        # check for access_token and get mfa_methods
        if 'access_token' in self.token_dic:
            response = self.client.get(self.base_url + self.api_prefix + f'/mfa/mfa/methods?filter%5BmethodType%5D={self.mfa_method}')
            if response.status_code == 200:
                mfa_dic = response.json()
            else:
                raise DKBRoboError(f'Login failed: getting mfa_methods failed. RC: {response.status_code}')
        else:
            raise DKBRoboError('Login failed: no 1fa access token.')

        self.logger.debug('api.Wrapper._get_mfa_methods() ended\n')
        return mfa_dic

    def _get_overview(self):
        """ get portfolio via api """
        self.logger.debug('api.Wrapper.get_portfolio()\n')

        # we calm the IDS system of DKB with two calls without sense
        self.client.get(self.base_url + self.api_prefix + '/terms-consent/consent-requests??filter%5Bportfolio%5D=DKB')
        response = self.client.get(self.base_url + self.api_prefix + '/config/users/me/product-display-settings')

        portfolio_dic = {}
        if response.status_code == 200:
            portfolio_dic['product_display'] = response.json()
            portfolio_dic['accounts'] = self._get_accounts()
            portfolio_dic['cards'] = self._get_cards()
            portfolio_dic['brokerage_accounts'] = self._get_brokerage_accounts()
            portfolio_dic['loands'] = self._get_loans()

        return self._build_account_dic(portfolio_dic)

    def _get_relationship_ids(self, position):
        """ get relationship ids from depot position """
        self.logger.debug('api.Wrapper._get_relationship_ids()\n')

        instrument_id = None
        quote_id = None
        if 'relationships' in position:
            if 'instrument' in position['relationships'] and 'data' in position['relationships']['instrument'] and 'id' in position['relationships']['instrument']['data']:
                instrument_id = position['relationships']['instrument']['data']['id']
            if 'quote' in position['relationships'] and 'data' in position['relationships']['quote'] and 'id' in position['relationships']['quote']['data']:
                quote_id = position['relationships']['quote']['data']['id']

        return instrument_id, quote_id

    def _get_token(self):
        """ get access token """
        self.logger.debug('api.Wrapper._get_token()\n')

        # login via API
        data_dic = {'grant_type': 'banking_user_sca', 'username': self.dkb_user, 'password': self.dkb_password, 'sca_type': 'web-login'}
        response = self.client.post(self.base_url + self.api_prefix + '/token', data=data_dic)
        if response.status_code == 200:
            self.token_dic = response.json()
        else:
            raise DKBRoboError(f'Login failed: 1st factor authentication failed. RC: {response.status_code}')
        self.logger.debug('api.Wrapper._get_token() ended\n')

    def _new_session(self):
        """ new request session for the api calls """
        self.logger.debug('api.Wrapper._new_session()\n')

        headers = {
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'DNT': '1',
            'Pragma': 'no-cache',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/112.0'}
        client = requests.session()
        client.headers = headers
        if self.proxies:
            client.proxies = self.proxies
            client.verify = False

        # get cookies
        client.get(self.base_url + '/login')

        # add csrf token
        if '__Host-xsrf' in client.cookies:
            headers['x-xsrf-token'] = client.cookies['__Host-xsrf']
            client.headers = headers

        self.logger.debug('api.Wrapper._new_session()\n ended')
        return client

    def _objectname_lookup(self, document):
        """ lookup object name """
        self.logger.debug('api.Wrapper._objectname_lookup()\n')

        object_name = None

        if 'cardId' in document['attributes']['metadata']:
            for _acc_id, acc_data in self.account_dic.items():
                if acc_data['id'] == document['attributes']['metadata']['cardId']:
                    object_name = f"{self._get_document_name(document['attributes']['metadata']['subject'])} {acc_data['account']}"
                    break
            if not object_name:
                _sinin, cardnr, _sinin = document['attributes']['fileName'].split('_', 2)
                object_name = f"{self._get_document_name(document['attributes']['metadata']['subject'])} {cardnr}"
        else:
            object_name = self._get_document_name(document['attributes']['metadata']['subject'])

        self.logger.debug('api.Wrapper._objectname_lookup()\n')
        return object_name

    def _print_2fa_confirmation(self, devicename):
        """ 2fa confirmation message """
        self.logger.debug('api.Wrapper._print_2fa_confirmation()\n')
        if devicename:
            print(f'check your banking app on "{devicename}" and confirm login...')
        else:
            print('check your banking app and confirm login...')

    def _process_challenge_response(self, response):
        """ get challenge dict with information on the 2nd factor """
        self.logger.debug('api.Wrapper._process_challenge_response()\n')
        challenge_id = None
        if response.status_code in (200, 201):
            challenge_dic = response.json()
            if 'data' in challenge_dic and 'id' in challenge_dic['data'] and 'type' in challenge_dic['data']:
                if challenge_dic['data']['type'] == 'mfa-challenge':
                    challenge_id = challenge_dic['data']['id']
                else:
                    raise DKBRoboError(f'Login failed:: wrong challenge type: {challenge_dic}')

            else:
                raise DKBRoboError(f'Login failed: challenge response format is other than expected: {challenge_dic}')
        else:
            raise DKBRoboError(f'Login failed: post request to get the mfa challenges failed. RC: {response.status_code}')

        return challenge_id

    def _process_userinput(self, device_num, device_list, _tmp_device_num, deviceselection_completed):
        self.logger.debug('api.Wrapper._process_userinput(%s)', _tmp_device_num)
        try:
            if int(_tmp_device_num) in device_list:
                deviceselection_completed = True
                device_num = int(_tmp_device_num)
            else:
                print('\nWrong input!')
        except Exception:
            print('\nInvalid input!')

        return device_num, deviceselection_completed

    def _select_mfa_device(self, mfa_dic):
        """ pick mfa_device from dictionary """
        self.logger.debug('_select_mfa_device()')
        device_num = 0

        if 'data' in mfa_dic and len(mfa_dic['data']) > 1:
            device_list = []
            deviceselection_completed = False
            while not deviceselection_completed:
                print('\nPick an authentication device from the below list:')
                # we have multiple devices to select
                for idx, device_dic in enumerate(mfa_dic['data']):
                    device_list.append(idx)
                    if 'attributes' in device_dic and 'deviceName' in device_dic['attributes']:
                        print(f"[{idx}] - {device_dic['attributes']['deviceName']}")
                _tmp_device_num = input(':')

                device_num, deviceselection_completed = self._process_userinput(device_num, device_list, _tmp_device_num, deviceselection_completed)

        self.logger.debug('_select_mfa_device() ended with: %s', device_num)
        return device_num

    def _update_token(self):
        """ update token information with 2fa iformation """
        self.logger.debug('api.Wrapper._update_token()\n')

        data_dic = {'grant_type': 'banking_user_mfa', 'mfa_id': self.token_dic['mfa_id'], 'access_token': self.token_dic['access_token']}
        response = self.client.post(self.base_url + self.api_prefix + '/token', data=data_dic)
        if response.status_code == 200:
            self.token_dic = response.json()
        else:
            raise DKBRoboError(f'Login failed: token update failed. RC: {response.status_code}')

    def get_credit_limits(self):
        """ get credit limits """
        self.logger.debug('api.Wrapper.get_credit_limits()\n')
        limit_dic = {}

        for _aid, account_data in self.account_dic.items():
            if 'limit' in account_data:
                if 'iban' in account_data:
                    limit_dic[account_data['iban']] = account_data['limit']
                elif 'maskedpan' in account_data:
                    limit_dic[account_data['maskedpan']] = account_data['limit']

        return limit_dic

    def get_standing_orders(self, uid=None):
        """ get standing orders """
        self.logger.debug('api.Wrapper.get_standing_orders()\n')

        so_list = []
        if uid:
            response = self.client.get(self.base_url + self.api_prefix + '/accounts/payments/recurring-credit-transfers' + '?accountId=' + uid)
            if response.status_code == 200:
                _so_list = response.json()
                so_list = self._filter_standing_orders(_so_list)

        else:
            raise DKBRoboError('get_standing_orders(): account-id is required')

        return so_list

    def get_transactions(self, transaction_url, atype, date_from, date_to, transaction_type):
        """ get transactions via API """
        self.logger.debug('api.Wrapper.get_transactions(%s, %s)\n', atype, transaction_type)

        transaction_list = []

        response = self.client.get(transaction_url)
        if response.status_code == 200:
            transaction_dic = response.json()
        else:
            self.logger.error('api.Wrapper._get_transactions(): RC is not 200 but %s', response.status_code)
            transaction_dic = {}

        if transaction_dic and 'data' in transaction_dic:
            if atype == 'account':
                transaction_list = self._filter_transactions(transaction_dic['data'], date_from, date_to, transaction_type)
                transaction_list = self._format_account_transactions(transaction_list)
            elif atype == 'creditcard':
                transaction_list = self._filter_transactions(transaction_dic['data'], date_from, date_to, transaction_type)
                transaction_list = self._format_card_transactions(transaction_list)
            elif atype == 'depot':
                transaction_list = self._format_brokerage_account(transaction_dic)

        self.logger.debug('api.Wrapper.get_transactions() ended\n')
        return transaction_list

    def login(self):
        """ login into DKB banking area and perform an sso redirect """
        self.logger.debug('api.Wrapper.login()\n')

        mfa_dic = {}

        # create new session
        self.client = self._new_session()

        # get token for 1fa
        self._get_token()

        # get mfa methods
        mfa_dic = self._get_mfa_methods()

        # pick mfa device from list
        device_number = self._select_mfa_device(mfa_dic)

        # we need a challege-id for polling so lets try to get it
        mfa_challenge_id = None
        if 'mfa_id' in self.token_dic and 'data' in mfa_dic:
            mfa_challenge_id, device_name = self._get_mfa_challenge_id(mfa_dic, device_number)
        else:
            raise DKBRoboError('Login failed: no 1fa access token.')

        # lets complete 2fa
        mfa_completed = False
        if mfa_challenge_id:
            mfa_completed = self._complete_2fa(mfa_challenge_id, device_name)
        else:
            raise DKBRoboError('Login failed: No challenge id.')

        # update token dictionary
        if mfa_completed and 'access_token' in self.token_dic:
            self._update_token()
        else:
            raise DKBRoboError('Login failed: mfa did not complete')

        if 'token_factor_type' not in self.token_dic:
            raise DKBRoboError('Login failed: token_factor_type is missing')

        if 'token_factor_type' in self.token_dic and self.token_dic['token_factor_type'] != '2fa':

            raise DKBRoboError('Login failed: 2nd factor authentication did not complete')

        # get account overview
        self.account_dic = self._get_overview()

        # redirect to legacy page
        self._do_sso_redirect()
        self.logger.debug('api.Wrapper.login() ended\n')
        return self.account_dic, None

    def logout(self):
        """ logout function """
        self.logger.debug('api.Wrapper.logout()\n')

    def scan_postbox(self, path, download_all, archive, prepend_date):
        """ scans the DKB postbox and creates a dictionary """
        self.logger.debug('api.Wrapper.scan_postbox() path: %s, download_all: %s, archive: %s, prepend_date: %s\n', path, download_all, archive, prepend_date)

        documents_dic = {}

        response = self.client.get(self.base_url + self.api_prefix + '/documentstorage/messages')
        if response.status_code == 200:
            msg_dic = response.json()

        response = self.client.get(self.base_url + self.api_prefix + '/documentstorage/documents?page%5Blimit%5D=1000')
        if response.status_code == 200:
            pb_dic = response.json()

        if msg_dic and pb_dic:
            documents_dic = self._filter_postbox(msg_dic, pb_dic, path, download_all, archive, prepend_date)

        return documents_dic
