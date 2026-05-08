module.exports = [
  {
    type: 'input',
    name: 'name',
    message:
      "Test target (snake_case, matches the module name). e.g. 'task_router'",
  },
  {
    type: 'select',
    name: 'kind',
    message: 'What is the test target?',
    choices: ['agent', 'collector', 'scoring', 'orchestrator', 'other'],
  },
];
