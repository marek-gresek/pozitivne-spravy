# Project conventions

- Public documentation describes text analysis and podcast scripts as using **OpenAI API**. Do not publish private deployment endpoints, network addresses, host paths, account identifiers or operational details.
- Keep the standard OpenAI Responses API as the public default. Deployment-specific values belong only in the ignored private environment.
- Never commit API keys, authentication tokens, private environment files, databases, backups, generated audio or logs. Scan both candidate files and Git history before publishing.
- Screenshots for documentation must show only the public interface and contain no private administration or authentication data.
- Preserve the allowed text models and `reasoning.effort: high`. Public reads must not invoke AI.
- Preserve article archives and podcast transcripts. Audio retention is 14 days; cleanup must remain confined to the dedicated audio directory and reject symbolic links.
- Run relevant offline tests and verify visible changes in a real browser. Do not claim a live pilot complete until its observation period has actually elapsed.
