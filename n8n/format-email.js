// n8n Code node: Run Once for All Items; after /prepare.
// Python already escapes all source content and creates both geographic sections.
const digest = $input.first().json;
return [{json: {
  ...digest,
  subject: digest.count ? `DevOps job alert: ${digest.count} new matches`
    : digest.warnings.length ? 'Job alert: no new matches; coverage incomplete'
    : 'No new jobs today',
  html: digest.html,
}}];
