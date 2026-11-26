const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const {verifyRepair,repaired,original,testSource}=require('./p2-fixture.cjs');
test('independent fixture verifier rejects incorrect code and changed tests',()=>{
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'lca-p2-fixture-'));
  try{
    fs.writeFileSync(path.join(root,'add.cjs'),original);
    fs.writeFileSync(path.join(root,'test-add.cjs'),testSource);
    assert.equal(verifyRepair(root),false);
    fs.writeFileSync(path.join(root,'add.cjs'),repaired);
    assert.equal(verifyRepair(root),true);
    fs.writeFileSync(path.join(root,'test-add.cjs'),'process.exit(0);');
    assert.equal(verifyRepair(root),false);
  }finally{fs.rmSync(root,{recursive:true,force:true});}
});
