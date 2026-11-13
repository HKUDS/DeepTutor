<?xml version="1.0" encoding="UTF-8"?>

<xs:schema 
  xmlns:xs="http://www.w3.org/2001/XMLSchema"
  xmlns="http://www.w3.org/1998/Math/MathML"
  targetNamespace="http://www.w3.org/1998/Math/MathML"
  elementFormDefault="qualified"
 >

<xs:annotation>
  <xs:documentation>
  This is an XML Schema module for the linear algebra part of content MathML.
  Author: St&#233;phane Dalmas, INRIA.
  </xs:documentation>
</xs:annotation>

<!-- "vector" -->

<xs:attributeGroup name="vector.attlist">
  <xs:attributeGroup ref="Common.attrib"/>
</xs:attributeGroup>

<xs:group name="vector.content">
  <xs:sequence>
    <xs:group ref="Content-expr.class"/>
  </xs:sequence>
</xs:group>

<xs:complexType name="vector.type">
  <xs:group ref="vector.content" minOccurs="1" maxOccurs="unbounded"/>
  <xs:attributeGroup ref="vector.attlist"/>
</xs:complexType>

<xs:element name="vector" type="vector.type"/>

<!-- "matrix" -->

<xs:attributeGroup name="matrix.attlist">
  <xs:attributeGroup ref="Common.attrib"/>
</xs:attributeGroup>

<xs:group name="matrix.content">
  <xs:sequence>
    <xs:element ref="matrixrow"/>
  </xs:sequence>
</xs:group>

<xs:complexType name="matrix.type">
  <xs:group ref="matrix.content"  minOccurs="1" maxOccurs="unbounded"/>
  <xs:attributeGroup ref="matrix.attlist"/>
</xs:complexType>

<xs:element name="matrix" type="matrix.type"/>

<!-- "matrixrow" -->

<xs:attributeGroup name="matrixrow.attlist">
  <xs:attributeGroup ref="Common.attrib"/>
</xs:attributeGroup>

<xs:group name="matrixrow.content">
  <xs:sequence>
    <xs:group ref="Content-expr.class"/>
  </xs:sequence>
</xs:group>

<xs:complexType name="matrixrow.type">
  <xs:group ref="matrixrow.content"  minOccurs="1" maxOccurs="unbounded"/>
  <xs:attributeGroup ref="matrixrow.attlist"/>
</xs:complexType>

<xs:element name="matrixrow" type="matrixrow.type"/>

<!-- "determinant" -->

<xs:attributeGroup name="determinant.attlist">
  <xs:attributeGroup ref="Definition.attrib"/>
  <xs:attributeGroup ref="Common.attrib"/>
</xs:attributeGroup>

<xs:complexType name="determinant.type">
  <xs:attributeGroup ref="determinant.attlist"/>
</xs:complexType>

<xs:element name="determinant" type="determinant.type"/>

<!-- "transpose" -->

<xs:attributeGroup name="transpose.attlist">
  <xs:attributeGroup ref="Definition.attrib"/>
  <xs:attributeGroup ref="Common.attrib"/>
</xs:attributeGroup>

<xs:complexType name="transpose.type">
  <xs:attributeGroup ref="transpose.attlist"/>
</xs:complexType>

<xs:element name="transpose" type="transpose.type"/>

<!-- "selector" -->

<xs:attributeGroup name="selector.attlist">
  <xs:attributeGroup ref="Definition.attrib"/>
  <xs:attributeGroup ref="Common.attrib"/>
</xs:attributeGroup>

<xs:complexType name="selector.type">
  <xs:attributeGroup ref="selector.attlist"/>
</xs:complexType>

<xs:element name="selector" type="selector.type"/>

<!-- "vectorproduct" -->

<xs:attributeGroup name="vectorproduct.attlist">
  <xs:attributeGroup ref="Definition.attrib"/>
  <xs:attributeGroup ref="Common.attrib"/>
</xs:attributeGroup>

<xs:complexType name="vectorproduct.type">
  <xs:attributeGroup ref="vectorproduct.attlist"/>
</xs:complexType>

<xs:element name="vectorproduct" type="vectorproduct.type"/>

<!-- "scalarproduct" -->

<xs:attributeGroup name="scalarproduct.attlist">
  <xs:attributeGroup ref="Definition.attrib"/>
  <xs:attributeGroup ref="Common.attrib"/>
</xs:attributeGroup>

<xs:complexType name="scalarproduct.type">
  <xs:attributeGroup ref="scalarproduct.attlist"/>
</xs:complexType>

<xs:element name="scalarproduct" type="scalarproduct.type"/>

<!-- "outerproduct" -->

<xs:attributeGroup name="outerproduct.attlist">
  <xs:attributeGroup ref="Definition.attrib"/>
  <xs:attributeGroup ref="Common.attrib"/>
</xs:attributeGroup>

<xs:complexType name="outerproduct.type">
  <xs:attributeGroup ref="outerproduct.attlist"/>
</xs:complexType>

<xs:element name="outerproduct" type="outerproduct.type"/>

<!-- And the group of everything -->

<xs:group name="Content-linear-algebra.class">
  <xs:choice>
     <xs:element ref="vector"/>
     <xs:element ref="matrix"/>
     <xs:element ref="determinant"/>
     <xs:element ref="transpose"/>
     <xs:element ref="selector"/>
     <xs:element ref="vectorproduct"/>
     <xs:element ref="scalarproduct"/>
     <xs:element ref="outerproduct"/>
  </xs:choice>
</xs:group>
</xs:schema>

<!--
  Copyright &#251; 2002 World Wide Web Consortium, (Massachusetts Institute
  of Technology, Institut National de Recherche en Informatique et en
  Automatique, Keio University). All Rights Reserved. See
  http://www.w3.org/Consortium/Legal/.
  -->
