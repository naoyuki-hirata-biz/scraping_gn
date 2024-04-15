"""
Test for Requests.

Usage:

pytest tests/test_create_csv_by_requests.py -s

"""

import os

import pytest

from csv_creator import CsvCreatorFactory, RequestsCsvCreator


class TestCreateCsvByRequests:
    """Test for requests."""
    @pytest.fixture
    def args(self):
        """init argumants."""
        args = {
            'uri': 'file:///opt/python/static/html/gnavi_list_01.html',
            'lib': 'requests',
            'filename': 'tests/results.csv',
            'shops': 50,
            'timeout': 90,
            'retry': 3,
        }

        if os.path.isfile(args['filename']):
            os.remove(args['filename'])

        return args

    def test_can_create_csv(self, args):
        """Test case to assert that a CSV file is output."""
        creator = CsvCreatorFactory().create_csv_creator(**args)
        assert isinstance(creator, RequestsCsvCreator)
        creator.create()
        assert os.path.isfile(args['filename'])
