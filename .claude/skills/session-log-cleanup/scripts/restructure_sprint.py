import os
import re
import subprocess
import sys
from collections import defaultdict

def run_cmd(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0 and "fatal: not under version control" not in result.stderr:
        print(f"Warning: Command '{cmd}' failed with: {result.stderr}")
    return result

def restructure_sprint(sprint_dir):
    if not os.path.exists(sprint_dir):
        print(f"Error: Directory {sprint_dir} does not exist.")
        sys.exit(1)

    sprint_dir = os.path.abspath(sprint_dir)
    
    # Create taxonomy directories
    dirs_to_create = ['logs', 'plans', 'verdicts', 'cells']
    for d in dirs_to_create:
        d_path = os.path.join(sprint_dir, d)
        if not os.path.exists(d_path):
            os.makedirs(d_path)
            print(f"Created {d_path}")

    # Regex for matching date-based files like 2026-06-11.md or 2026-06-11_something.md
    date_pattern = re.compile(r'^(\d{4}-\d{2}-\d{2})(?:.*)?\.md$')
    
    # Also look in logs/ and verdicts/ in case the script was run previously and we just want to backfill the README
    files_to_check = []
    
    # Check root
    for f in os.listdir(sprint_dir):
        if os.path.isfile(os.path.join(sprint_dir, f)):
            files_to_check.append(f)
            
    # Check logs
    logs_dir = os.path.join(sprint_dir, 'logs')
    if os.path.exists(logs_dir):
        for f in os.listdir(logs_dir):
            if os.path.isfile(os.path.join(logs_dir, f)):
                files_to_check.append(os.path.join('logs', f))
    
    daily_sessions = defaultdict(list)
    
    for relative_path in files_to_check:
        filename = os.path.basename(relative_path)
        if filename == 'README.md' or filename == 'RESEARCH_LOG.md':
            continue
            
        match = date_pattern.match(filename)
        if match:
            # It's a daily session log
            date_str = match.group(1)
            # Only process if it's at the root (needs moving)
            if relative_path == filename:
                daily_sessions[date_str].append(filename)
            else:
                # Already in logs, just record the date for range calculation
                if date_str not in daily_sessions:
                    daily_sessions[date_str] = []
        elif relative_path == filename and filename.endswith('.md'):
            # Default to verdicts for other md files at root
            target_path = os.path.join(sprint_dir, 'verdicts', filename)
            run_cmd(f'cd "{sprint_dir}" && git mv "{filename}" "verdicts/{filename}" || mv "{filename}" "verdicts/{filename}"')
            print(f"Moved {filename} to verdicts/")

    # Process daily sessions that are at root
    for date_str, sessions in daily_sessions.items():
        if not sessions:
            continue
            
        if len(sessions) == 1:
            filename = sessions[0]
            new_filename = f"{date_str}.md"
            run_cmd(f'cd "{sprint_dir}" && git mv "{filename}" "logs/{new_filename}" || mv "{filename}" "logs/{new_filename}"')
            print(f"Moved {filename} to logs/{new_filename}")
        else:
            # Multiple sessions
            sessions.sort()
            index_content = f"# Sessions — {date_str}\n\nMultiple sessions this day. Each is a separate handover; this is the index.\n\n"
            for i, filename in enumerate(sessions, 1):
                name_without_ext = filename[:-3]
                if name_without_ext == date_str:
                    slug = "main"
                else:
                    slug = name_without_ext[11:].strip('_')
                
                new_filename = f"{date_str}_{i:02d}_{slug}.md"
                run_cmd(f'cd "{sprint_dir}" && git mv "{filename}" "logs/{new_filename}" || mv "{filename}" "logs/{new_filename}"')
                print(f"Moved {filename} to logs/{new_filename}")
                index_content += f"{i}. [{i:02d} — {slug}]({new_filename})\n"
                
            index_path = os.path.join(sprint_dir, 'logs', f"{date_str}_index.md")
            with open(index_path, 'w') as f:
                f.write(index_content)
            print(f"Created index file {index_path}")

    # Generate skeleton README.md and RESEARCH_LOG.md if they don't exist
    readme_path = os.path.join(sprint_dir, 'README.md')
    research_log_path = os.path.join(sprint_dir, 'RESEARCH_LOG.md')
    
    dates = sorted(daily_sessions.keys())
    date_range = f"{dates[0]} → {dates[-1]}" if dates else "TBD → TBD"
    sprint_name = os.path.basename(sprint_dir)
    sprint_num = sprint_name.split('_')[-1] if '_' in sprint_name else "N"
    
    try:
        next_sprint = int(sprint_num) + 1
    except ValueError:
        next_sprint = "N+1"

    if not os.path.exists(readme_path):
        readme_content = f"""# Sprint {sprint_num} — <theme>

**Dates:** {date_range} · **Status:** ✅ Closed · **Next:** [sprint_{next_sprint}](../sprint_{next_sprint}/README.md)

> <one-paragraph framing: the core question / goal of the sprint.>

### Folder map
- **`RESEARCH_LOG.md`** — the linear question ledger (how the thinking evolved, by sequence).
- **`logs/`** — dated session handovers.
- **`plans/`** — forward-looking design/plan docs.
- **`verdicts/`** — findings, reports, issues, playbooks.
- **`cells/`** — notebook-cell artifacts.

### Headline outcomes
- **<verdict>** — <one line, banked-or-falsified first>.

## Roadmap & Goals
- [x] <completed item>

## Carried over
- [ ] <deferred item>
"""
        with open(readme_path, 'w', encoding='utf-8') as f:
            f.write(readme_content)
        print(f"Generated skeleton README.md for {sprint_name}")

    if not os.path.exists(research_log_path):
        research_content = f"""# Sprint {sprint_num} — Research Log

This is the linear train-of-thought for the sprint, tracking questions and their resolution.

## Thread A: <Topic>
1. **<Question>?** → <Outcome>. [link](link)

---

## Open meta-questions
- <Open question>
"""
        with open(research_log_path, 'w', encoding='utf-8') as f:
            f.write(research_content)
        print(f"Generated skeleton RESEARCH_LOG.md for {sprint_name}")
            
    print("Cleanup script complete! Please review verdicts/ to see if any files should be moved to plans/ or cells/, and fill in the missing details in RESEARCH_LOG.md and README.md.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python restructure_sprint.py <path_to_sprint_folder>")
        sys.exit(1)
    
    restructure_sprint(sys.argv[1])
