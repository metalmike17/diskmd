Name:           diskmd
Version:        0.1.1
Release:        1%{?dist}
Summary:        Drive health for Linux, in plain English
License:        MIT
URL:            https://github.com/metalmike17/diskmd
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch
BuildRequires:  python3-devel
BuildRequires:  desktop-file-utils
BuildRequires:  libappstream-glib
Requires:       python3 >= 3.10
Requires:       smartmontools
Recommends:     polkit
Recommends:     fio
Recommends:     python3-pyside6
Suggests:       libnotify

%description
diskmd makes SMART data readable. It checks every drive in your PC, explains in
plain English whether it is healthy and what to do about it, and detects USB
enclosures automatically. It also checks link speed (an SSD stuck on USB 2.0, an
NVMe running at x2), scans the kernel log for I/O errors, runs SMART self-tests,
benchmarks with fio, tracks wear and temperature over time, can alert you daily,
and can check whether a used drive's SMART history looks altered.

diskmd only reads SMART data. It never writes to or reconfigures a drive.

%prep
%autosetup -n %{name}-%{version}

%build

%install
install -d %{buildroot}%{python3_sitelib} %{buildroot}%{_bindir}
cp -r diskmd %{buildroot}%{python3_sitelib}/
find %{buildroot} -name __pycache__ -prune -exec rm -rf {} +
install -Dm755 packaging/diskmd-launcher %{buildroot}%{_bindir}/diskmd
install -Dm644 data/io.github.metalmike17.DiskMD.desktop -t %{buildroot}%{_datadir}/applications/
install -Dm644 data/io.github.metalmike17.DiskMD.metainfo.xml -t %{buildroot}%{_metainfodir}/
install -Dm644 data/io.github.metalmike17.DiskMD.svg -t %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/io.github.metalmike17.DiskMD.desktop
appstream-util validate-relax --nonet %{buildroot}%{_metainfodir}/io.github.metalmike17.DiskMD.metainfo.xml || :
PYTHONPATH=%{buildroot}%{python3_sitelib} %{python3} -m unittest discover -s tests

%files
%license LICENSE
%doc README.md
%{_bindir}/diskmd
%{python3_sitelib}/diskmd/
%{_datadir}/applications/io.github.metalmike17.DiskMD.desktop
%{_metainfodir}/io.github.metalmike17.DiskMD.metainfo.xml
%{_datadir}/icons/hicolor/scalable/apps/io.github.metalmike17.DiskMD.svg

%changelog
* Thu Nov 05 2026 metalmike17 <michaeljg0717@gmail.com> - 0.1.1-1
- Native-window hint, DiskMD naming polish

* Thu Nov 05 2026 metalmike17 <michaeljg0717@gmail.com> - 0.1.0-1
- Initial package
