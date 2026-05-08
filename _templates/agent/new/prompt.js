module.exports = [
  {
    type: 'input',
    name: 'name',
    message:
      "Agent name (snake_case, no '_agent' suffix). e.g. 'subnet_discovery'",
  },
  {
    type: 'input',
    name: 'role',
    message: 'One-line role description for this agent',
  },
];
