# Security policy

## Supported versions

Security fixes target the [latest fork release](https://github.com/dev-zetta/LSCamoflash/releases/latest). Check whether a newer release already addresses the problem before reporting it.

## Report a vulnerability privately

Use **[Report a vulnerability](https://github.com/dev-zetta/LSCamoflash/security/advisories/new)** in this fork's GitHub Security Advisories. Private vulnerability reporting is enabled. Do not include exploit details or credentials in public issues.

Include the affected component, LSCamoflash version, exact camera firmware, reproduction steps, expected impact and a minimal proof of concept where available. Remove unrelated credentials and device identifiers. Reports are handled by volunteer maintainers; response times are not guaranteed.

Allow time for investigation and a fix before public disclosure. Coordinate any disclosure through the private report.

## Scope

This policy covers the fork's build and backup scripts, SD runtime, web interface and packaged service integration. Vendor firmware, third-party projects and cloud services may need reports to their respective maintainers; describe their role when relevant.

The SD runtime uses the camera's stock boot hook and does not imply that persistent settings remain untouched. Keep HTTP, Telnet, FTP and unauthenticated RTSP on a trusted network, replace default passwords and disable unused services. See [configuration](docs/configuration.md#passwords-and-services) for the actual account and service defaults.
