# etcd-haproxy

This project use etcd as service registry. The `wrapper.py` generate a HAProxy configfile
from a template. HAProxy reloads only by adding new servers in the backend-section. The
weight of servers will be changed on the fly and write the configfile (without reload).

## dependencies
* [python-etcd](https://github.com/jplana/python-etcd)
* [etcd](https://github.com/coreos/etcd) (single-node or cluster)
* [haproxy](http://www.haproxy.org/) version 1.5 is recommended

## first steps
* start etcd
* start the `dummyApp.py`
* start `wrapper.py`
