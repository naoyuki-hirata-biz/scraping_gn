"""
Script to export Csv.

Usage

optional arguments:
  -h, --help            show this help message and exit
  --uri URI             gnavi url
  --lib {requests,selenium}
                        use requests or selenium library (default: requests)
  --filename FILENAME   output csv filename (default: results.csv)
  --shops SHOPS         Maximum number of shops acquired (default: 50, max: 50)
  --timeout TIMEOUT     Timeout time to find the element (seconds) (default: 90)
  --retry RETRY         Number of retries (default: 3)


Test

pytest tests/test_create_csv_by_requests.py -s
pytest tests/test_create_csv_by_selenium.py -s

"""

import argparse

from csv_creator import CsvCreatorFactory


def get_args():
    """Return arguments."""
    parser = argparse.ArgumentParser(description='Usage')
    parser.add_argument('--uri', help='gnavi url', required=True, type=str)
    parser.add_argument('--lib', help='use requests or selenium library (default: requests)', choices=['requests', 'selenium'], default='requests')
    parser.add_argument('--filename', help='output csv filename (default: results.csv)', type=str, default='results.csv')
    parser.add_argument('--shops', help='Maximum number of shops acquired (default: 50, max: 50)', type=int, default=50)
    parser.add_argument('--timeout', help='Timeout time to find the element (seconds) (default: 90)', type=int, default=90)
    parser.add_argument('--retry', help='Number of retries (default: 3)', type=int, default=3)

    args = parser.parse_args()
    if args.shops < 1 or args.shops > 50:
        args.shops = 50
    return vars(args)


def main():
    """Main processing."""
    arguments = get_args()

    creator = CsvCreatorFactory().create_csv_creator(**arguments)
    creator.create()


if __name__ == '__main__':
    main()
