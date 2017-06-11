import usocket
import ujson
try:
    import ussl
    SUPPORT_SSL = True
except ImportError:
    ussl = None
    SUPPORT_SSL = False

SUPPORT_TIMEOUT = hasattr(usocket.socket, 'settimeout')
CONTENT_TYPE_JSON = 'application/json'

# Read all http headers from a socket
def parse_headers(sock):
    headers = {}
    line = b""
    while line != b'\r\n':
        line = sock.readline()
        if line.strip():
            name, value = line.strip().split(b': ')
            headers[name] = value.strip()
    return headers

class Response(object):
    def __init__(self, status_code, raw, resp_headers):
        self.status_code = status_code
        self.raw = raw
        self._content = False
        self.encoding = 'utf-8'
        self.headers = resp_headers

    @property
    def content(self):
        if self._content is False:
            self._content = self.raw.read()
            self.raw.close()
            self.raw = None

        return self._content

    @property
    def text(self):
        content = self.content

        return str(content, self.encoding) if content else ''

    def close(self):
        if self.raw is not None:
            self._content = None
            self.raw.close()
            self.raw = None

    def multipart(self):
        if b'Content-Type' in self.headers and 'multipart/x-mixed-replace' in self.headers[b'Content-Type']:
            boundary = str(self.headers[b'Content-Type'],'utf-8').split('boundary=')[1]
            #print(boundary)
            block = b""
            while boundary not in block:
                block += self.raw.read(1)
            block += self.raw.read(2)
            while True:
                headers = parse_headers(self.raw)
                block = b""
                while boundary not in block:
                    block += self.raw.read(1)
                block += self.raw.read(2)

                r = Response(self.status_code, None, headers)
                r._content = block
                yield r

    def json(self):
        return ujson.loads(self.text)

    def raise_for_status(self):
        if 400 <= self.status_code < 500:
            raise OSError('Client error: %s' % self.status_code)
        if 500 <= self.status_code < 600:
            raise OSError('Server error: %s' % self.status_code)


# Adapted from upip
def request(method, url, json=None, timeout=None, headers=None, follow_redirect=True):
    urlparts = url.split('/', 3)
    proto = urlparts[0]
    host = urlparts[2]
    urlpath = '' if len(urlparts) < 4 else urlparts[3]

    if proto == 'http:':
        port = 80
    elif proto == 'https:':
        port = 443
    else:
        raise OSError('Unsupported protocol: %s' % proto[:-1])

    if ':' in host:
        host, port = host.split(':')
        port = int(port)

    if json is not None:
        content = ujson.dumps(json)
        content_type = CONTENT_TYPE_JSON
    else:
        content = None

    ai = usocket.getaddrinfo(host, port)
    addr = ai[0][4]

    sock = usocket.socket()

    if timeout is not None:
        assert SUPPORT_TIMEOUT, 'Socket does not support timeout'
        sock.settimeout(timeout)

    sock.connect(addr)

    if proto == 'https:':
        assert SUPPORT_SSL, 'HTTPS not supported: could not find ussl'
        sock = ussl.wrap_socket(sock)

    sock.write('%s /%s HTTP/1.0\r\nHost: %s\r\n' % (method, urlpath, host))

    if headers is not None:
        for header in headers.items():
            sock.write('%s: %s\r\n' % header)

    if content is not None:
        sock.write('content-length: %s\r\n' % len(content))
        sock.write('content-type: %s\r\n' % content_type)
        sock.write('\r\n')
        sock.write(content)
    else:
        sock.write('\r\n')

    l = sock.readline()
    protover, status, msg = l.split(None, 2)

    # Collect headers
    headers = parse_headers(sock)

    # Handle redirects
    if int(status) in [301, 301] and b'Location' in headers:
        if 'http' not in headers[b'Location']:
            # relative redirect
            redirect = proto+"://"+host+"/"+str(headers[b'Location'], 'utf-8')
        else:
            redirect = str(headers[b'Location'], 'utf-8')
        return request(method, redirect, json, timeout, headers, follow_redirect)

    return Response(int(status), sock, headers)


def get(url, **kwargs):
    return request('GET', url, **kwargs)


def post(url, **kwargs):
    return request('POST', url, **kwargs)
