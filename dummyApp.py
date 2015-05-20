#!/usr/bin/python

import os
import sys
import web
import etcd
import json
import socket
import getopt
import random

urls        = ('/','root')

class Realserver:
    name = ''
    ip = ''
    port = ''

    def __init__(self, name, ip, port):
        self.name    = name
        self.ip      = ip
        self.port    = int(port)
#        self.version = version

    def __str__(self):
        return json.dumps(vars(self),sort_keys=True, indent=4)



class root:
    def __init__(self):
        try:
            etcd_client = etcd.Client(host='127.0.0.1', port=2379, protocol='http')
        except:
            print 'no etcd'
        self.hello = os.environ['app_name'] + ' ' + os.environ['app_version']
 
    def GET(self):
        return self.hello


class WebApp(web.application):
    def run(self, ip='0.0.0.0', port=8080, *middleware):
        func = self.wsgifunc(*middleware)
        server = web.httpserver.runsimple(func, (ip, port))
        return server


def main(argv):

    app_version = ''
    app_name    = ''

    try:
        opts, args = getopt.getopt(argv,'n:V:t:')
    except getopt.GetoptError:
        print 'test.py -n <app name> -V <app version> [-t <ttl>]'
        sys.exit(2)

    if len(opts) < 2:
        print 'test.py -n <app name> -V <app version> [-t <ttl>]'
        sys.exit(2)

    ttl = 3600
    for opt, arg in opts:
        if opt in ('-V'):
            app_version = arg
        elif opt in ('-n'):
            app_name = arg
        elif opt in ('-t'):
            ttl = int(arg)

    etcdPrefix = '/haproxy/backends/{}/'.format(app_name)
    

    port = random.randint(10000, 30000)
    ip   = '127.' + str(random.randint(0,255)) + '.' + str(random.randint(0,255)) + '.' + str(random.randint(0,255))

    try:
        name      = '{}-{}_{}'.format(socket.gethostname(), app_version, port)
        etcdKey   = '{}{}/realserver/{}'.format(etcdPrefix, app_version, name)
        etcdValue = Realserver(name, ip, port)

        etcd_client = etcd.Client(host='127.0.0.1', port=2379, protocol='http')
        etcd_client.write(etcdKey, etcdValue, ttl=ttl)

    except Exception as e:
        print 'Error: {}'.format(e)
        sys.exit()

    try:
        # refresh weight
        weight = etcd_client.read(etcdPrefix + app_version + '/weight').value
        etcd_client.write(etcdPrefix + app_version + '/weight', weight, ttl=ttl)
        print 'weight for ' + app_name + ' (' + app_version + ') is ' + weight 
    except etcd.EtcdKeyNotFound:
        # write default weight
        print 'No default weight found. Set default weight to 0'
        etcd_client.write(etcdPrefix + app_version + '/weight', '0' , ttl=ttl)
        

    print 'Starting ' + app_name + ' ('  + app_version + ')'
    os.environ['app_name']    = app_name
    os.environ['app_version'] = app_version
    os.environ['port']        = str(port)
    os.environ['ip']          = ip

    app = WebApp(urls, globals())
    app.run(ip=ip,port=port)


if __name__ == "__main__":
    main(sys.argv[1:])
