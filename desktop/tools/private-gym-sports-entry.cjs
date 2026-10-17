'use strict';
// Local development review only. Normal application launches do not enable CDP.
const {app}=require('electron');
app.commandLine.appendSwitch('remote-debugging-address','127.0.0.1');
app.commandLine.appendSwitch('remote-debugging-port','9541');
require('./private-gym-art-entry.cjs');
