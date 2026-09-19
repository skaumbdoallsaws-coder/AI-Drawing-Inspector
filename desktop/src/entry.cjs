'use strict';
// Keep the accepted rendering diagnostic as an explicit separate entry point.
// The ordinary launch now goes through the protected managed runtime.
if (process.argv.includes('--application')) {
  process.argv = process.argv.filter(value => value !== '--application');
  require('./application-main.cjs');
} else if (process.argv.includes('--preview')) {
  process.argv = process.argv.filter(value => value !== '--preview');
  require('./main.cjs');
} else require('./runtime-main.cjs');
