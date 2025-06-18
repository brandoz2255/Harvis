1. Remove Dangling Images (Untagged/Intermediate)

These are layers left behind after builds:


docker image prune

2. Remove Stopped Containers

Free up space by removing containers that are not running:


docker container prune

3. Remove Unused Images (Not Used by Any Container)

This will delete images not referenced by any container (running or stopped):


docker image prune -a

    Warning: This removes ALL images not used by any container, including images you built for experiments but aren't using now.
