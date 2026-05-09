module.exports = [
  {
    type: 'input',
    name: 'name',
    message:
      "Plug-in name (snake_case, no '_agent' suffix). e.g. 'micro_fish' or 'cricket_brain'",
  },
  {
    type: 'input',
    name: 'role',
    message: 'One-line description of what this plug-in does',
  },
  {
    type: 'input',
    name: 'out_dir',
    message: 'Output directory (absolute or relative). Plug-in lives OUTSIDE the swarm repo.',
    initial: 'plugins',
  },
];
