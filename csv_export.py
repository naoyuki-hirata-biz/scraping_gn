import argparse

from builder import CsvBuilderFactory


def get_args():
    parser = argparse.ArgumentParser(description='Usage')
    parser.add_argument('--uri', help="gnavi url (If using static files, specify 'file:///opt/python/static/html/gnavi_list_01.html')", required=True, type=str)
    # TODO: default: requests
    parser.add_argument('--lib', help='use requests or selenium library (default: selenium)', choices=['requests', 'selenium'])
    parser.add_argument('--filename', help='output csv filename (default: results.csv)', type=str)
    parser.add_argument('--shops', help='Maximum number of shops acquired (default: 50)', type=int)
    parser.add_argument('--timeout', help='Timeout time to find the element (seconds) (default: 90)', type=int)
    parser.add_argument('--retry', help='Number of retries (default: 3)', type=int)

    args = parser.parse_args()
    args.lib = args.lib or 'selenium'
    args.filename = args.filename or 'results.csv'
    args.shops = args.shops or 50
    args.timeout = args.timeout or 90
    args.retry = args.retry or 3
    return vars(args)

# ==============================
# メイン処理
# ==============================
args = get_args()

builder = CsvBuilderFactory().create_csv_builder(**args)
builder.build().write_csv()
