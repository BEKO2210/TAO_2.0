module.exports = [
  {
    type: 'input',
    name: 'name',
    message:
      "Scorer name (snake_case, no '_score' suffix). e.g. 'liquidity_risk'",
  },
  {
    type: 'input',
    name: 'description',
    message: 'One-line description of what this scorer measures',
  },
];
