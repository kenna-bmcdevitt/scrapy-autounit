import copy

from scrapy import Item
from scrapy.http import Request, Response
from scrapy.spiders import CrawlSpider


class Parser:
    def _clean_headers(self, headers):
        # Use the new setting, if empty, try the deprecated one
        excluded = self.spider.settings.get('AUTOUNIT_DONT_RECORD_HEADERS', [])
        if not excluded:
            excluded = self.spider.settings.get('AUTOUNIT_EXCLUDED_HEADERS', [])
        auth_headers = ['Authorization', 'Proxy-Authorization']
        # Use the new setting, if empty, try the deprecated one
        included = self.spider.settings.get('AUTOUNIT_RECORD_AUTH_HEADERS', [])
        if not included:
            included = self.spider.settings.get('AUTOUNIT_INCLUDED_AUTH_HEADERS', [])
        excluded.extend([h for h in auth_headers if h not in included])
        for header in excluded:
            headers.pop(header, None)
            headers.pop(header.encode(), None)

    def _clean_from_jmes(self, full_obj, jmes_path, keys=[], nested_obj={}):
        keys = keys or jmes_path.split('.')
        nested_obj = nested_obj or full_obj

        raw_key = keys.pop(0)
        key = raw_key.strip('[]')
        if not nested_obj.get(key):
            return

        if '[]' in raw_key:
            if not keys:
                nested_obj[key] = []
            for item in nested_obj[key]:
                self._clean_from_jmes(
                    full_obj, jmes_path, keys=list(keys), nested_obj=item)
        else:
            if not keys:
                nested_obj.pop(key)
            else:
                self._clean_from_jmes(
                    full_obj, jmes_path, keys=keys, nested_obj=nested_obj[key])

    def _parse_meta(self, request):
        meta = {}
        for key, value in request.get('meta').items():
            if key != '_autounit_cassette':
                meta[key] = self.parse_object(value)
        dont_record = self.spider.settings.get('AUTOUNIT_DONT_RECORD_META', [])
        for path in dont_record:
            self._clean_from_jmes(meta, path)
        return meta

    def _request_to_dict(self, request):
        _request = request.to_dict(spider=self.spider)
        if not _request['callback']:
            _request['callback'] = 'parse'
        elif isinstance(self.spider, CrawlSpider):
            rule = request.meta.get('rule')
            if rule is not None:
                _request['callback'] = self.spider.rules[rule].callback
        self._clean_headers(_request['headers'])
        _request['meta'] = self._parse_meta(_request)
        return _request

    def _response_to_dict(self, response):
        return {
            'cls': '{}.{}'.format(
                type(response).__module__,
                getattr(type(response), '__qualname__', None) or
                getattr(type(response), '__name__', None)
            ),
            'url': response.url,
            'status': response.status,
            'body': response.body,
            'headers': dict(response.headers),
            'flags': response.flags,
            'encoding': response.encoding,
        }

    def spider_attrs(self):
        to_filter = {'crawler', 'settings', 'start_urls'}

        if isinstance(self.spider, CrawlSpider):
            to_filter |= {'rules', '_rules'}

        dont_record_attrs = set(
            self.spider.settings.get('AUTOUNIT_DONT_RECORD_SPIDER_ATTRS', []))
        to_filter |= dont_record_attrs

        return {
            k: v for k, v in self.spider.__dict__.items()
            if k not in to_filter
        }

    def parse_response(self, response_obj):
        request = self._request_to_dict(response_obj.request)
        response = self._response_to_dict(response_obj)
        return request, response

    def parse_object(self, _object):
        if isinstance(_object, Request):
            return self._request_to_dict(_object)
        elif isinstance(_object, Response):
            return self.parse_object(self._response_to_dict(_object))
        elif isinstance(_object, (dict, Item)):
            for k, v in _object.items():
                _object[k] = self.parse_object(v)
        elif isinstance(_object, list):
            for i, v in enumerate(_object):
                _object[i] = self.parse_object(v)
        elif isinstance(_object, tuple):
            _object = tuple([self.parse_object(o) for o in _object])
        return _object

    def parse_callback_output(self, output):
        parsed = []
        original = []
        for elem in output:
            original.append(elem)
            is_request = isinstance(elem, Request)
            if is_request:
                data = self._request_to_dict(elem)
            else:
                data = self.parse_object(copy.deepcopy(elem))
            parsed.append({
                'type': 'request' if is_request else 'item',
                'data': data
            })
        return iter(original), parsed

    def deprecated_settings(self):
        mapping = {
            'AUTOUNIT_SKIPPED_FIELDS': 'AUTOUNIT_DONT_TEST_OUTPUT_FIELDS',
            'AUTOUNIT_REQUEST_SKIPPED_FIELDS': 'AUTOUNIT_DONT_TEST_REQUEST_ATTRS',
            'AUTOUNIT_EXCLUDED_HEADERS': 'AUTOUNIT_DONT_RECORD_HEADERS',
            'AUTOUNIT_INCLUDED_AUTH_HEADERS': 'AUTOUNIT_RECORD_AUTH_HEADERS',
            'AUTOUNIT_INCLUDED_SETTINGS': 'AUTOUNIT_RECORD_SETTINGS',
        }
        message = "DEPRECATED: '{}' is going to be removed soon. Please use '{}' instead."
        warnings = []
        for old, new in mapping.items():
            if not self.spider.settings.get(old):
                continue
            warnings.append(message.format(old, new))
        return warnings
