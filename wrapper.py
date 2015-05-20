#!/usr/bin/python -W all

import etcd
import time
import json
import socket
import hashlib
import subprocess

# global variables
RECV_SIZE = 1024

class Realserver:
    name = ''
    ip = ''
    port = ''
    version = None

    def __init__(self, name, ip, port, version = ''):
        self.name    = name
        self.ip      = ip
        self.port    = port

    def __str__(self):
        return json.dumps(vars(self),sort_keys=True, indent=4)

    def getHAProxyString(self):
        connect = '{}:{}'.format(self.ip, self.port)
        return '     server {} {} maxconn 32 check weight '.format(self.name, connect)


def getWeight(component, version):
    key  = '/haproxy/backends/{}/{}/weight'.format(component,version)
    try:
        weight = client.read(key)
        return int(weight.value)
    except etcd.EtcdKeyNotFound:
        return 0


def sendToSocket(socketFile, command):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

    if not command.endswith('\n'):
        command += '\n'

    try:
        s.connect(socketFile)
    except IOError as e:
        print "I/O error({0}): {1}".format(e.errno, e.strerror)
        return None

    s.send(command)
    result = ''
    buf = ''
    buf = s.recv(RECV_SIZE)
    while buf:
      result += buf
      buf = s.recv(RECV_SIZE)
    s.close()

    return result


def getStats(socketFile):
    result = sendToSocket(socketFile, 'show stat')
    if result is None:
        return {}

    lines = result.split('\n')
    state, servers = {}, {}
    for line in lines:
        values = line.split(',')

        if values[0].startswith('#') or values[0] == '':
            continue

        if values[1] == 'FRONTEND':
            continue
        elif values[1] == 'BACKEND':
            continue

        site, hostname, status, weight, code = values[0], values[1], values[17], values[18], values[36]

        if site not in state:
            state[site] = {}

        state[site][hostname] = {
            'status': status,
            'weight': int(weight),
            'code': code,
        }

    return state


# stop running haproxy
subprocess.Popen(['/usr/bin/pkill', 'haproxy'])


client     = etcd.Client(host='127.0.0.1', port=2379, protocol='http')
pid        = 90000000
checksum   = None
template   = 'template/haproxy.template'
socketFile = '/tmp/haproxy.sock'
running    = False

while True:
    backends = {}

    config = ''
    http_frontend = ''
    http_backend = ''
    doReload = False
        

    try:
        r = client.read('/haproxy/backends', recursive=True, sorted=True)
    except:
        time.sleep(20)
        print 'etcd is not available! sleep for 20 seconds'
        continue

    for child in r.children:
        # don't get empty backends and not the 'weight' keys
        if child.value is not None and child.key.endswith('weight') is False:
            # the key has this format
            # /haproxy/backends/<application name>/<version>/realserver/<servername>
            tmp       = child.key.split('/')
            app       = tmp[3]
            version   = tmp[4]
            name      = tmp[6]
            j         = json.loads(child.value)
            j['name'] = name 
            server    = Realserver(**j)

            if app not in backends:
                backends[app] = {}

            if version not in backends[app]:
                backends[app][version] = []

            backends[app][version].append(server)
        elif child.value is None:
            # delete keys without value
            print 'delete key without value %s' % child.key
            client.delete(child.key, dir=True)

    
    # write routing 
    for app in backends:
        http_frontend = http_frontend + '   use_backend ' + app + '     ' + 'if {{ hdr_dom(host) str -m {}.domain }}\n'.format(app)
    
    state = getStats(socketFile)
    command = []

    # write backends
    for app in backends:
        http_backend = http_backend + 'backend ' + app + '\n'
        for version in backends[app]:
            ratio  = getWeight(app, version)
            num    = len(backends[app][version])
            weight = int(((float(ratio) / 100.0) / num) * 100)

            for server in backends[app][version]:
                http_backend = http_backend + server.getHAProxyString() + str(weight) + '\n'

                # check if the keys are included in dictionary
                #   no try-except-block needed -> lazy evaluation
                if app in state.keys() and server.name in state[app].keys() and doReload == False:
                    # change only the weight, if needed
                    if state[app][server.name]['weight'] != weight:
                        command.append('set weight {}/{} {}'.format( app, server.name, weight))
                else:
                    doReload = True
        
    # load template and generate new config
    f = open(template, 'r')
    config = f.read()
    config = config.replace('###HTTP_FRONTEND###', http_frontend)
    config = config.replace('###BACKENDS###', http_backend)
    config = config.replace('###SOCKET###', socketFile)
    f.close()
    
    md5 = hashlib.md5()
    md5.update(config)
    new_sum = md5.hexdigest()

    if checksum != new_sum:
        print 'write new config'
        f = open('haproxy.cfg', 'wb')
        f.write(config)
        f.close()
        checksum = new_sum

    if doReload is True or running is False:
        print 'Reload config'
        pipe    = subprocess.Popen(['/usr/sbin/haproxy', '-f', 'haproxy.cfg', '-q', '-sf', str(pid)])
        pid     = pipe.pid
        running = True

    if doReload is False:
        if command:
            print 'Reconfigure HAProxy on the fly'
            sendToSocket(socketFile, '; '.join(command))

    print 'sleep'
    time.sleep(5)
