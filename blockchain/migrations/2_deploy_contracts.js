const Invoice = artifacts.require("Invoice");

module.exports = function (deployer) {
  deployer.deploy(Invoice);
};  