#!/bin/bash
cd "/Users/ts24/Desktop/Data TS24 Claude/05_SCRIPTS"
exec /usr/bin/python3 "/Users/ts24/Desktop/Data TS24 Claude/05_SCRIPTS/ts24_watcher.py" >> "/tmp/ts24_watcher.log" 2>&1
