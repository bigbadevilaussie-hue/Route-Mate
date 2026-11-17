# Basic iMac and Terminal gotchas

This is a practical setup note for Nick's iMac development workflow. It is not a generic macOS manual.

## Machine context

- iMac14,2 (27-inch, Late 2013)
- macOS Sonoma installed using OpenCore Legacy Patcher (OCLP)
- 3.4 GHz Intel Core i5
- 32 GB RAM
- Intel/NVIDIA-era graphics and older Intel platform

The machine is useful for development and testing, but it is not the definition of Route-Mate's performance. Fairness is based on fixed logical work budgets, not equal run time.

## Terminal basics

- Commands are shell commands. Run them from the stated working directory.
- Check the current directory with: pwd
- List files with: ls -la
- Check Git state with: git status --short --branch
- Check the active Python with: python3 --version and which python3
- Check the active compiler with: clang --version
- Check available disk space with: df -h
- Stop a running foreground command with Control-C.
- Do not paste shell prompts (for example, nick@imac %) as part of a command.
- Do not type explanatory text into Terminal.
- A command that appears to do nothing may still be running; inspect the process/output before launching a duplicate.

## Nick-specific shell preferences

- Prefer short, direct commands.
- For non-trivial Python, write a script to /tmp and run it from the repository directory.
- Avoid zsh heredocs and multi-line paste sequences that can trigger continuation prompts.
- Avoid commands that rely on fragile shell quoting when a small script is clearer.
- Give one action at a time when troubleshooting; wait for the result before issuing the next step.
- Do not assume a command succeeded. Check its output and Git status.

## zsh continuation prompt gotcha

If Terminal displays a continuation prompt such as dquote>, quote>, pipe>, or a secondary prompt, the shell is waiting for the rest of an unfinished command. It has not necessarily hung.

- Press Control-C to cancel the incomplete command.
- Re-enter a simpler command with balanced quotes.
- Do not keep pasting more unrelated commands into the unfinished input.

## OCLP and macOS caution

- This iMac runs an unsupported macOS generation through OCLP. OS updates, bootloader changes and graphics/network patches can behave differently from a supported Mac.
- Do not suggest firmware, EFI, APFS, bootloader or OS changes as casual troubleshooting steps.
- Before any destructive disk, partition, EFI or boot command, explain the exact target and consequence and obtain explicit confirmation.
- Keep project work and backups separate from OS migration work.
- Do not assume paths, mounted volume names or Python environments. Verify them first.

## Build and performance caution

- Do not use elapsed time as the optimiser's work budget.
- Record engine version, input hash, seeds and evaluation count.
- A slower iMac must receive the same configured search opportunity as a faster computer; it may take longer to finish.
- Avoid CPU-specific assumptions in the algorithm. Optional acceleration must preserve the defined results or be clearly labelled as a different execution mode.
