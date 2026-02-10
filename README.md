VLA Dispatcher
==============

    Authors: Sarah Burke-Spolaor, Frank Schinzel, Jayce Dowell

Overview
--------
The VLA Dispatcher monitors the Jansky Very Large Array (VLA) metadata broadcast
(MCAF multicast stream) and identifies observation events matching specified
project and intent criteria.  When a matching scan is found, the dispatcher
writes a JSON command file that is consumed by the eLWA notification server
(`fcn_server.py` in the `eLWA_triggering` package) for distribution to LWA
stations.

The dispatcher is one component of the eLWA coordination system:

```
VLA MCAF Stream --> dispatcher.py --> incoming.json --> fcn_server.py (eLWA_triggering)
```


Prerequisites
-------------
 1. Python 2.7+ (dispatcher and support libraries use Python 2 conventions)
 2. Network access to the VLA MCAF multicast group (`239.192.3.2:53001`)
 3. The `eLWA_triggering` package (provides the notification server that
    consumes the dispatcher's output)


Files and Organization
----------------------
| File | Description |
|---|---|
| `vla_dispatcher/dispatcher.py` | Main dispatcher; monitors MCAF stream and writes commands |
| `vla_dispatcher/mcaf_library.py` | MCAF multicast client and VLA configuration parser |
| `vla_dispatcher/obsdocxml_parser.py` | Auto-generated XML parser for VLA obsdoc documents |
| `vla_dispatcher/angles.py` | Angle conversion and formatting utilities |
| `vla_dispatcher/jdcal.py` | Julian date / calendar date conversion utilities |
| `client_tools/client_software.py` | Legacy example TCP client for receiving dispatches |
| `service/vla-dispatcher.service` | systemd service file |


Configuration
-------------
The dispatcher is configured entirely via command-line arguments:

| Argument | Default | Description |
|---|---|---|
| `-i`, `--intent` | `''` | Trigger on scans whose intent contains this substring |
| `-p`, `--project` | `''` | Trigger on scans whose project ID contains this substring |
| `-d`, `--dispatch` | off | Enable dispatch mode (write command files); without this flag the dispatcher only logs matching scans |
| `-c`, `--command-file` | `incoming.json` | Path to the JSON command file consumed by `fcn_server.py` |
| `-v`, `--verbose` | off | Enable verbose (DEBUG) logging |


Running
-------

### Listening Mode (Dry Run)

To monitor the MCAF stream and log matching scans without dispatching:

```bash
cd vla_dispatcher
python dispatcher.py --intent OBSERVE_PULSAR_RAW --project TSKY
```

### Dispatch Mode

To monitor and write command files for consumption by `fcn_server.py`:

```bash
cd vla_dispatcher
python dispatcher.py \
    --intent OBSERVE_PULSAR_RAW \
    --dispatch \
    --command-file /home/op1/eLWA/incoming.json
```

The `--command-file` path must match the `--command-file` argument given to
`fcn_server.py` in the `eLWA_triggering` package.

### systemd Service

A systemd service file is provided in `service/vla-dispatcher.service`.  To
install:

```bash
sudo cp service/vla-dispatcher.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable vla-dispatcher.service
sudo systemctl start vla-dispatcher.service
```

The service file should be edited to reflect the correct intent filter and
command file path for your deployment.


Event Types
-----------
The dispatcher generates three event types:

| Type | Description |
|---|---|
| `ELWA_SESSION` | A scan matching the intent filter is available for observation.  Includes position, duration, and the VLA configuration URL. |
| `ELWA_READY` | First scan of a new scheduling block for a matching project. |
| `ELWA_DONE` | A matching project has finished (source is `FINISH`). |


Command File Format
-------------------
The dispatcher writes a JSON file with the following fields:

| Field | Type | Description |
|---|---|---|
| `notice_type` | string | One of `ELWA_SESSION`, `ELWA_READY`, `ELWA_DONE` |
| `event_id` | int | Serial number derived from current UTC time |
| `project_id` | string | VLA project ID |
| `scan_id` | int | VLA scan number |
| `scan_intent` | string | Scan intent string |
| `event_t` | float | Event time (UNIX timestamp) |
| `event_source` | string | Source name |
| `event_ra` | float | Right Ascension in degrees (or -1 for READY/DONE) |
| `event_dec` | float | Declination in degrees (or -1 for READY/DONE) |
| `event_duration` | float | Observation duration in seconds (or -1 for READY/DONE) |
| `config_url` | string | URL to the VLA configuration XML |

The file is deleted by `fcn_server.py` after it has been read.  The dispatcher
waits for the file to be consumed before writing the next command.
