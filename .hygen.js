module.exports = {
  templates: `${__dirname}/_templates`,
  helpers: {
    snake: (s) =>
      s
        .replace(/([a-z])([A-Z])/g, '$1_$2')
        .replace(/[\s\-]+/g, '_')
        .toLowerCase(),
    pascal: (s) =>
      s
        .replace(/[_\-\s]+/g, ' ')
        .replace(/\s(.)/g, ($1) => $1.toUpperCase())
        .replace(/\s/g, '')
        .replace(/^(.)/, ($1) => $1.toUpperCase()),
    upper: (s) => s.toUpperCase(),
  },
};
