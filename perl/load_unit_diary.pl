#!/usr/bin/perl
#
# load_unit_diary.pl
#
# Loads the nightly unit diary fixed-width feed into MARINE_MASTER.
# Runs ahead of PROMELIG in the nightly cycle.
#
# 1996  original
# 2001  reduction-in-grade indicator added
# 2003  grade effective date added for the web tier
# 2009  moved off the old DBI wrapper
#
# NOTE: field offsets track MARREC.CPY. If the copybook changes, this
# breaks silently -- there is no length validation on the input record.
#

use strict;
use warnings;
use DBI;

my $FEED = $ENV{'UD_FEED'} || '/prod/feeds/unitdiary.dat';

my %OFFSETS = (
    edipi            => [   0, 10 ],
    last_nm          => [  10, 26 ],
    first_nm         => [  36, 20 ],
    middle_init      => [  56,  1 ],
    grade            => [  57,  3 ],
    grade_num        => [  60,  2 ],
    pmos             => [  62,  4 ],
    dt_last_promo    => [  66,  8 ],
    dt_orig_promo    => [  74,  8 ],
    grade_eff_dt     => [  82,  8 ],
    pebd             => [  90,  8 ],
    dt_enlist        => [  98,  8 ],
    red_in_grade_ind => [ 106,  1 ],
);

my $dbh = DBI->connect( $ENV{'DSN'}, $ENV{'DBUSER'}, $ENV{'DBPASS'},
                        { RaiseError => 1, AutoCommit => 0 } );

open( my $fh, '<', $FEED ) or die "cannot open $FEED: $!";

my $n = 0;
my $skipped = 0;

while ( my $line = <$fh> ) {
    chomp $line;
    next if $line =~ /^\s*$/;

    my %rec;
    for my $f ( keys %OFFSETS ) {
        my ( $off, $len ) = @{ $OFFSETS{$f} };
        $rec{$f} = substr( $line, $off, $len );
        $rec{$f} =~ s/^\s+|\s+$//g;
    }

    # Records arriving from the reserve component feed do not carry a
    # grade effective date. Leave it null rather than defaulting -- the
    # web service falls back to date of last promotion when it is absent.
    if ( $rec{grade_eff_dt} =~ /^0*$/ ) {
        $rec{grade_eff_dt} = undef;
    }

    # A reduction sets the indicator but the feed does not restate the
    # original promotion date. If it is absent, carry forward whatever
    # is already on the master record.
    if ( $rec{red_in_grade_ind} eq 'Y' && $rec{dt_orig_promo} =~ /^0*$/ ) {
        $skipped++;
        delete $rec{dt_orig_promo};
    }

    upsert_master( $dbh, \%rec );
    $n++;

    if ( $n % 5000 == 0 ) {
        $dbh->commit;
    }
}

$dbh->commit;
close($fh);

print "load_unit_diary: loaded $n records, $skipped carried forward\n";

$dbh->disconnect;
exit 0;

sub upsert_master {
    my ( $dbh, $rec ) = @_;

    my @cols = grep { defined $rec->{$_} } keys %$rec;
    my $set  = join( ', ', map { "$_ = ?" } @cols );
    my @vals = map { $rec->{$_} } @cols;

    my $sth = $dbh->prepare_cached(
        "UPDATE MARINE_MASTER SET $set WHERE EDIPI = ?" );
    my $rows = $sth->execute( @vals, $rec->{edipi} );

    if ( $rows == 0 ) {
        my $collist = join( ', ', @cols );
        my $binds   = join( ', ', map { '?' } @cols );
        my $ins     = $dbh->prepare_cached(
            "INSERT INTO MARINE_MASTER ($collist) VALUES ($binds)" );
        $ins->execute(@vals);
    }
}
