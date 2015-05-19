#!/usr/bin/python

import os
import etcd
import time
import json
import socket
import hashlib
import commands
import subprocess
from collections import namedtuple

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

def getStats(SOCKET):
    status = commands.getstatusoutput('echo "show stat" | socat {} stdio'.format(SOCKET))
    lines = status[1].split('\n')
    state, servers = {}, {}
    for l in lines:

        vals = l.split(',')
        if SOCKET in l or len(vals) == 1:
            print 'debug %s' % l
            continue

        if vals[0].startswith('#') or vals[0] == '':
            continue

        if vals[1] == 'FRONTEND':
            end = 'f'
            continue
        elif vals[1] == 'BACKEND':
            end = 'b'
            continue

        site, hostname, status, weight, code = vals[0], vals[1], vals[17], vals[18], vals[36]

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


client = etcd.Client(host='127.0.0.1', port=2379, protocol='http')

pid      = 90000000
checksum = None
template = 'template/haproxy.template'
SOCKET   = '/tmp/haproxy.sock'

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
            server  = Realserver(**j)

            if app not in backends:
                backends[app] = {}

            if version not in backends[app]:
                backends[app][version] = []

            backends[app][version].append(server)
    
    # write routing 
    for app in backends:
        http_frontend = http_frontend + '   acl         ' + app + '     ' + 'hdr_dom(host) -i ' + app + '.spreadshirt.test\n'
        http_frontend = http_frontend + '   use_backend ' + app + '     ' + 'if ' + app + '\n\n'
    
    state = getStats(SOCKET)
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
                try:
                    if server.name in state[app].keys() and doReload == False:
                        # change only the weight, if needed
                        if state[app][server.name]['weight'] != weight:
                            command.append('set weight {}/{} {}'.format( app, server.name, weight))
                    else:
                        doReload = True
                except Exception as e:
                    doReload = True
                    print state
                    print 'Error in write backends: %s' % e
        
    # load template and generate new config
    f = open(template, 'r')
    config = f.read()
    config = config.replace('###HTTP_FRONTEND###', http_frontend)
    config = config.replace('###BACKENDS###', http_backend)
    f.close()
    
    md5 = hashlib.md5()
    md5.update(config)
    new_sum = md5.hexdigest()

    if checksum != new_sum:
        f = open('haproxy.cfg', 'wb')
        f.write(config)
        f.close()
        checksum = new_sum

    if doReload is True:
        print 'Reload config'
        pipe = subprocess.Popen(['/usr/sbin/haproxy', '-f', 'haproxy.cfg', '-q', '-sf', str(pid)])
        pid  = pipe.pid
        print 'done'

    if doReload is False:
        if command:
            print 'Reconfigure HAProxy on the fly'
            print command
            status = commands.getstatusoutput('echo "%s" | socat stdio %s' % ( '; '.join( command ), SOCKET ) )
            print status

    print 'sleep'
    time.sleep(5)
