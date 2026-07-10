// Idempotent MongoDB bootstrap for the retail-stock-take demo.
// Executed via `docker exec -i retail-mongo mongosh --quiet < rs-init.js`
// from scripts/setup.sh. Initiates the replica set and ensures the
// inventory collection has changeStreamPreAndPostImages enabled.

const replSet = process.env.MONGO_REPLICA_SET || 'rs0';
const replHost = process.env.MONGO_REPL_HOST || 'mongo:27017';
const dbName = process.env.APP_DB_NAME || 'retail_demo';
const collName = process.env.APP_COLLECTION || 'inventory_captures';

function log(msg) {
  print('[mongo-init] ' + msg);
}

// 1. Replica set (idempotent).
let needsInit = false;
try {
  const status = rs.status();
  log("replica set '" + status.set + "' already initiated.");
} catch (e) {
  if (e.codeName === 'NotYetInitialized' || e.code === 94) {
    needsInit = true;
  } else {
    throw e;
  }
}

if (needsInit) {
  log("initiating replica set '" + replSet + "' on " + replHost + '...');
  rs.initiate({
    _id: replSet,
    members: [{ _id: 0, host: replHost }],
  });

  let elected = false;
  for (let i = 0; i < 60 && !elected; i++) {
    try {
      if (rs.isMaster().ismaster) {
        elected = true;
        break;
      }
    } catch (e) {}
    sleep(500);
  }
  if (!elected) {
    throw new Error('primary never elected after 30s');
  }
  log('primary elected.');
}

// 2. Inventory collection with changeStreamPreAndPostImages.
const appDb = db.getSiblingDB(dbName);
const cols = appDb.getCollectionNames();

if (!cols.includes(collName)) {
  appDb.createCollection(collName, {
    changeStreamPreAndPostImages: { enabled: true },
  });
  log("collection '" + dbName + '.' + collName + "' created with pre/post images.");
} else {
  const info = appDb.getCollectionInfos({ name: collName })[0] || {};
  const opts = info.options || {};
  const enabled =
    opts.changeStreamPreAndPostImages &&
    opts.changeStreamPreAndPostImages.enabled;
  if (!enabled) {
    appDb.runCommand({
      collMod: collName,
      changeStreamPreAndPostImages: { enabled: true },
    });
    log('enabled pre/post images on existing collection.');
  } else {
    log('pre/post images already enabled.');
  }
}

// 3. Verify.
const verifyInfo = appDb.getCollectionInfos({ name: collName })[0] || {};
const verifyEnabled =
  verifyInfo.options &&
  verifyInfo.options.changeStreamPreAndPostImages &&
  verifyInfo.options.changeStreamPreAndPostImages.enabled;
if (!verifyEnabled) {
  throw new Error('pre/post images not enabled after bootstrap');
}

log('done.');
