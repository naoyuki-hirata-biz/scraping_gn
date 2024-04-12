import argparse

from builder import CsvBuilderFactory


def get_args():
    parser = argparse.ArgumentParser(description='Usage')
    parser.add_argument('--uri', help="gnavi url (default: 'file:///opt/python/static/html/gnavi_list_01.html')", type=str)
    parser.add_argument('--lib', help='use requests or selenium library (default: requests)', choices=['requests', 'selenium'])
    parser.add_argument('--filename', help='output csv filename (default: results.csv)', type=str)
    parser.add_argument('--shops', help='Maximum number of shops acquired (default: 50, max: 50)', type=int)
    parser.add_argument('--timeout', help='Timeout time to find the element (seconds) (default: 90)', type=int)
    parser.add_argument('--retry', help='Number of retries (default: 3)', type=int)

    args = parser.parse_args()
    args.uri = args.uri or 'file:///opt/python/static/html/gnavi_list_01.html'
    args.lib = args.lib or 'requests'
    args.filename = args.filename or 'results.csv'
    if args.shops is None or args.shops < 1 or args.shops > 50:
        args.shops = 50

    args.timeout = args.timeout or 90
    args.retry = args.retry or 3
    return vars(args)

# ==============================
# メイン処理
# ==============================
args = get_args()

builder = CsvBuilderFactory().create_csv_builder(**args)
builder.build().write_csv()
