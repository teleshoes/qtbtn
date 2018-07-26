#!/usr/bin/perl
use strict;
use warnings;

my $binDest = "/usr/local/bin";

sub run(@);

sub main(@){
  run "sudo", "cp", "qtbtn.py", $binDest;
}

sub run(@){
  print "@_\n";
  system @_;
}

&main(@ARGV);
