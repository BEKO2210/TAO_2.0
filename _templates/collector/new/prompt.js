module.exports = [
  {
    type: 'input',
    name: 'name',
    message:
      "Collector name (snake_case). e.g. 'github_repos', 'market_data'",
  },
  {
    type: 'input',
    name: 'description',
    message: 'One-line description for this collector',
  },
];
