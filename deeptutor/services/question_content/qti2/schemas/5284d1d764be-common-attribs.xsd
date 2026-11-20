<?xml version="1.0" encoding="UTF-8"?>

<xs:schema 
  xmlns:xs="http://www.w3.org/2001/XMLSchema"
  xmlns="http://www.w3.org/1998/Math/MathML"
  xmlns:xlink="http://www.w3.org/1999/xlink"
  targetNamespace="http://www.w3.org/1998/Math/MathML"
  elementFormDefault="qualified"
>

<xs:annotation>
  <xs:documentation>
  This is the common attributes module for MathML.
  Author: St&#233;phane Dalmas, INRIA.
  </xs:documentation>
</xs:annotation>


<xs:import namespace="http://www.w3.org/1999/xlink" schemaLocation="xlink-href.xsd"/>
<xs:import/> <!-- import any foreign namespace -->


<!-- The type of "class" is from the XHTML modularization with Schema
     document -->
<xs:attributeGroup name="Common.attrib">
  <xs:attribute name="class" type="xs:NMTOKENS"/>
  <xs:attribute name="style" type="xs:string"/>
  <xs:attribute name="xref" type="xs:IDREF"/>
  <xs:attribute name="id" type="xs:ID"/>
  <xs:attribute ref="xlink:href"/>
  <!-- allow attributes from foreign namespaces, and don't check them -->
  <xs:anyAttribute namespace="##other" processContents="skip"/>
</xs:attributeGroup>

</xs:schema>
<!--
  Copyright &#251; 2002 World Wide Web Consortium, (Massachusetts Institute
  of Technology, Institut National de Recherche en Informatique et en
  Automatique, Keio University). All Rights Reserved. See
  http://www.w3.org/Consortium/Legal/.
  -->
