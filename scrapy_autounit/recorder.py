import os
import random
import shutil
import sys

from scrapy.commands.genspider import sanitize_module_name

from .cassette import Cassette
from .parser import Parser
from .utils import get_base_path


TEST_TEMPLATE = """# THIS IS A GENERATED FILE
# Generated by: {command}  # noqa: E501
import os
import unittest
from glob import glob

from scrapy_autounit.player import Player


class AutoUnit(unittest.TestCase):
	def test__{test_name}(self):
		_dir = os.path.dirname(os.path.abspath(__file__))
		fixtures = glob(os.path.join(_dir, "*.bin"))
		for fixture in fixtures:
			player = Player.from_fixture(fixture)
			player.playback()


if __name__ == '__main__':
	unittest.main()
"""

class Recorder(Parser):
	def __init__(self, spider):
		self.spider = spider
		self.settings = spider.settings
		self.spider_name = sanitize_module_name(spider.name)
		self.spider_init_attrs = self.spider_attrs()

		self.fixture_counters = {}
		self._set_max_fixtures()

		self.base_path = get_base_path(self.settings)
		self._create_dir(self.base_path, exist_ok=True)
		self._clear_fixtures()

	@classmethod
	def update_fixture(cls, cassette, path):
		with open(path, 'wb') as outfile:
			outfile.write(cassette.pack())

	def _set_max_fixtures(self):
		self.max_fixtures = self.settings.getint('AUTOUNIT_MAX_FIXTURES_PER_CALLBACK', default=10)
		if self.max_fixtures < 10:
			self.max_fixtures = 10

	def _get_test_dir(self, callback_name):
		components = [self.base_path, 'tests', self.spider_name]
		extra = self.settings.get('AUTOUNIT_EXTRA_PATH')
		if extra:
			components.append(extra)
		components.append(callback_name)
		test_dir = None
		for comp in components:
			test_dir = os.path.join(test_dir, comp) if test_dir else comp
			self._create_dir(test_dir, parents=True, exist_ok=True)
			init_file = os.path.join(test_dir, '__init__.py')
			with open(init_file, 'a'):
				os.utime(init_file, None)
		return test_dir

	def _create_dir(self, path, parents=False, exist_ok=False):
		try:
			if parents:
				os.makedirs(path)
			else:
				os.mkdir(path)
		except OSError:
			if not exist_ok:
				raise

	def _clear_fixtures(self):
		path = os.path.join(self.base_path, 'tests', self.spider_name)
		shutil.rmtree(path, ignore_errors=True)

	def _get_fixture_name(self, index):
		default_name = 'fixture%s.bin' % index

		attr = self.settings.get('AUTOUNIT_FIXTURE_NAMING_ATTR', None)
		if not attr:
			return default_name

		value = getattr(self.spider, attr, None)
		if not value:
			msg = (
				"Could not find '{attr}' attribute in spider. "
				'Using default fixture naming.'
			)
			self.spider.logger.warning(msg.format(attr=attr))
			return default_name

		return 'fixture_{attr}_{index}.bin'.format(attr=value, index=index)

	def _add_sample(self, index, test_dir, cassette):
		filename = self._get_fixture_name(index)
		path = os.path.join(test_dir, filename)
		cassette.filename = filename
		with open(path, 'wb') as outfile:
			outfile.write(cassette.pack())

	def _write_test(self, path, callback_name):
		command = 'scrapy {}'.format(' '.join(sys.argv))
		test_path = os.path.join(path, 'test_fixtures.py')
		test_name = self.spider_name + '__' + callback_name
		test_code = TEST_TEMPLATE.format(test_name=test_name, command=command)
		#with open(str(test_path), 'w') as f:
		#	f.write(test_code)

	def new_cassette(self, response_obj):
		request, response = self.parse_response(response_obj)
		return Cassette(
			spider=self.spider,
			request=request,
			response=response,
			init_attrs=self.spider_init_attrs,
			input_attrs=self.spider_attrs(),
		)

	def record(self, cassette, output):
		original, parsed = self.parse_callback_output(output)

		cassette.output_data = parsed
		cassette.output_attrs = self.spider_attrs()

		callback_name = cassette.request['callback']
		callback_counter = self.fixture_counters.setdefault(callback_name, 0)
		self.fixture_counters[callback_name] += 1

		test_dir = self._get_test_dir(callback_name)

		index = 0
		if callback_counter < self.max_fixtures:
			index = callback_counter + 1
		else:
			r = random.randint(0, callback_counter)
			if r < self.max_fixtures:
				index = r + 1

		if index != 0:
			self._add_sample(index, test_dir, cassette)

		#if index == 1:
		#	self._write_test(test_dir, callback_name)

		return original
