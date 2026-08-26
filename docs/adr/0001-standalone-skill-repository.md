# Keep the Skill repository standalone

The public Skill includes its own minimal Warcraft Logs client instead of depending on the private `wcl-coach` project or a new shared package. This duplicates a small transport layer, but makes SkillHub installation self-contained and keeps the report-dataset model independent from personal coaching workflows.
