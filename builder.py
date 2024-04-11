from __future__ import annotations

import math
import os
import re
import shutil
import time
from abc import abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pandas as pd
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


@dataclass
class Shop:
    name: str = ''
    tel: str = ''
    email: str = ''
    prefecture: str = ''
    city: str = ''
    street: str = ''
    building: str = ''
    gn_url: str = ''
    official_url: str = ''

    def parse_address(self, address):
        pattern = r'(東京都|北海道|(?:京都|大阪)府|.{2,3}県)?(.+?)(\d.*)'
        match = re.match(pattern, address)
        self.prefecture = match.group(1)
        self.city = match.group(2)
        self.street = match.group(3)

    def secure(self):
        return self.official_url.startswith('https')

    def to_list(self):
        return [self.name, self.tel, self.email, self.prefecture, self.city, self.street, self.building, self.official_url, self.secure()]

class CsvBuilder:
    TIMEZONE = timezone(timedelta(hours=+9), 'JST')

    @abstractmethod
    def build(self) -> CsvBuilder:
        pass

    @abstractmethod
    def write_csv(self) -> CsvBuilder:
        pass

class CsvBuilderFactory:
    @staticmethod
    def create_csv_builder(**kwargs):
        lib = kwargs['lib']
        if lib == 'requests':
            # TODO:
            raise ValueError(f'Unknown lib: {lib}')
        elif lib == 'selenium':
            return SeleniumCsvBuilder(**kwargs)
        else:
            raise ValueError(f'Unknown type: {lib}')

class SeleniumCsvBuilder(CsvBuilder):
    def __init__(self, **kwargs):
        self.driver = None
        self.wait = None
        self.shops = []

        self.filename = kwargs['filename']
        self.uri = kwargs['uri']
        self.limit = kwargs['shops']
        self.timeout = kwargs['timeout']
        self.retry = kwargs['retry']

    # Override
    def build(self) -> CsvBuilder:
        self.__setUp()

        self.__set_gn_url_of_shops()
        self.__set_shop_details()

        self.__tearDown()
        return self

    # Override
    def write_csv(self) -> CsvBuilder:
        print('INFO ', datetime.now(self.TIMEZONE), 'CSVファイルを出力します')
        rows = [shop.to_list() for shop in self.shops]
        df = pd.DataFrame(rows, columns=['店舗名', '電話番号', 'メールアドレス', '都道府県', '市区町村', '番地', '建物名', 'URL', 'SSL'])
        df.to_csv(self.filename, encoding="utf-8_sig", index=False)
        print('INFO ', datetime.now(self.TIMEZONE), 'CSVファイルを出力しました')
        return self

    def __setUp(self):
        service = Service(executable_path='/usr/bin/chromedriver')
        options = webdriver.ChromeOptions()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        self.driver = webdriver.Chrome(service=service, options=options)
        self.wait = WebDriverWait(driver=self.driver, timeout=self.timeout)

        if (os.path.isfile(self.filename)):
            os.remove(self.filename)
        if (self.uri.startswith('file:///opt/python/static/html/')):
            shutil.unpack_archive('static/html.zip', 'static/html')

    def __set_gn_url_of_shops(self):
        print('INFO ', datetime.now(self.TIMEZONE), f'検索結果の上位{self.limit}件のURLを取得します')

        page = 1
        max_page = math.ceil(self.limit / 20)  # 1ページあたり20件

        self.driver.get(self.uri)
        while page <= max_page:
            url_selector = 'article > div.style_title___HrjW > a.style_titleLink__oiHVJ'
            self.wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, url_selector)))
            elems = self.driver.find_elements(By.CSS_SELECTOR, url_selector)
            [self.shops.append(Shop(gn_url=elems[i].get_attribute('href'))) for i in range(len(elems))]
            if len(self.shops) >= self.limit:
                break

            next_page_link_selector = '#__next > div > div.layout_body__LvaRc > main > div.style_pageNation__AZy1A > nav > ul > li:nth-last-child(2) > a'
            self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, next_page_link_selector)))
            next_page_link = self.driver.find_element(By.CSS_SELECTOR, next_page_link_selector)
            next_page_link.click()
            page += 1
            time.sleep(3)

        self.shops = self.shops[:self.limit]
        print('INFO ', datetime.now(self.TIMEZONE), f'検索結果の上位{self.limit}件のURLを取得しました')

    def __find_shop_name(self):
        shop_name_id = 'info-name'
        self.wait.until(EC.visibility_of_element_located((By.ID, shop_name_id)))
        elem = self.driver.find_element(By.ID, shop_name_id)
        return elem.text

    def __find_shop_tel(self):
        tel_selector = '#info-phone span.number'
        self.wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, tel_selector)))
        elem = self.driver.find_element(By.CSS_SELECTOR, tel_selector)
        return elem.text

    def __find_shop_email(self):
        elems = self.driver.find_elements(By.CSS_SELECTOR, '#info-table > table > tbody a[href^=mailto]')
        return elems[0].get_attribute('href').replace('mailto:', '') if elems else ''

    def __find_shop_address(self):
        return self.driver.find_element(By.CSS_SELECTOR, '#info-table > table > tbody p.adr > span.region').text

    def __find_shop_building(self):
        elems = self.driver.find_elements(By.CSS_SELECTOR, '#info-table > table > tbody p.adr > span.locality')
        return elems[0].text if elems else ''

    def __find_shop_official_url(self):
        official_url = ''
        ## 「お店のホームページ」からURLを取得する
        url_selector = '#info-table > table > tbody a.url'
        elems = self.driver.find_elements(By.CSS_SELECTOR, url_selector)
        if elems:
            # 動的にhref属性が生成されるまで待機
            self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, f'{url_selector}:first-child[href^="http"]')))
            for k in range(self.retry):
                try:
                    # 別タブで開かれる
                    elems[0].click()
                    self.wait.until(EC.number_of_windows_to_be(2))
                    handles = self.driver.window_handles
                    self.driver.switch_to.window(handles[1])
                    official_url = self.driver.current_url
                    self.driver.close()
                    self.driver.switch_to.window(handles[0])
                    break
                except TimeoutException:
                    print('WARN ', datetime.now(self.TIMEZONE), '     ', f'お店のホームページから店舗URLを取得できませんでした({k + 1}回目)')
                    time.sleep(3)

        ## 「お店のホームページ」リンクからURLを取得できなかった場合、「オフィシャルページ」アイコンからURL取得を試みる
        if not official_url:
            elems = self.driver.find_elements(By.CSS_SELECTOR, '#sv-site > li > a')
            if elems:
                for l in range(self.retry):
                    try:
                        # 別タブで開かれる
                        elems[0].click()
                        self.wait.until(EC.number_of_windows_to_be(2))
                        handles = self.driver.window_handles
                        self.driver.switch_to.window(handles[1])
                        official_url = self.driver.current_url
                        self.driver.close()
                        self.driver.switch_to.window(handles[0])
                        break
                    except TimeoutException:
                        print('WARN ', datetime.now(self.TIMEZONE), '     ', f'オフィシャルページから店舗URLを取得できませんでした({l + 1}回目)')
                        time.sleep(3)

        return official_url

    def __set_shop_details(self):
        print('INFO ', datetime.now(self.TIMEZONE), '店舗詳細を取得します')

        limit = len(self.shops)
        for i, shop in enumerate(self.shops):
            has_error = True
            for j in range(self.retry):
                try:
                    self.driver.get(shop.gn_url)
                    has_error = False
                    break
                except TimeoutException:
                    print('WARN ', datetime.now(self.TIMEZONE), '     ', f'アクセス時にタイムアウトになりました({j + 1}回目)', shop.gn_url)
                    time.sleep(3)
            if has_error:
                print('ERROR', datetime.now(self.TIMEZONE), '     ', 'アクセスできませんでした', shop.gn_url)
                exit()

            # 店舗名
            shop.name = self.__find_shop_name()
            print('DEBUG', datetime.now(self.TIMEZONE), f'{str(i + 1).rjust(len(str(limit)))}/{limit}', shop.name, shop.gn_url)
            # 電話番号
            shop.tel = self.__find_shop_tel()
            # メールアドレス
            shop.email = self.__find_shop_email()
            # 住所
            shop.parse_address(self.__find_shop_address())
            # 建物名
            shop.building = self.__find_shop_building()
            # URL
            shop.official_url = self.__find_shop_official_url()

        print('INFO ', datetime.now(self.TIMEZONE), '店舗詳細を取得しました')

    def __tearDown(self):
        if os.path.isdir('static/html'):
            shutil.rmtree('static/html')

        self.driver.close()
        self.driver.quit()
